"""
百度手写OCR批改策略实现

方案：百度手写OCR识别（带坐标）→ 本地规则引擎批改 → 错误坐标映射 → 结果输出

核心流程：
1. 百度 OAuth 2.0 鉴权，获取 access_token（缓存30天）
2. 调用 handwriting API 识别手写文字，返回行级 location
3. 规则引擎逐句匹配标准译文，检测错误
4. 将错误文本映射回 OCR 行 → 填充 BoundingBox
5. 组装 GradingResult 返回
"""

import json
import time
import base64
import os
import re
import urllib.parse
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

import requests
from PIL import Image

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grader_base import (
    GradingStrategy, GradingInput, GradingResult,
    SentenceAnalysis, ErrorItem, BoundingBox,
    ErrorType, Confidence, GradingStatus,
    GradingException, APIException, ParseException,
)


# ── 辅助数据结构 ─────────────────────────────────────

@dataclass
class OCRLine:
    """百度 OCR 返回的单行识别结果"""
    text: str           # 识别文字
    bbox: BoundingBox   # 在图片中的位置
    confidence_avg: float = 0.0  # 行置信度平均值


# ── 百度手写OCR GradingStrategy 实现 ─────────────────

class BaiduOCRGrader(GradingStrategy):
    """
    百度手写文字识别 + 规则引擎批改

    使用百度 handwriting API 识别手写文字（含行级坐标），
    然后用本地规则引擎进行文言文翻译批改。
    """

    # 百度 API 端点
    AUTH_URL = "https://aip.baidubce.com/oauth/2.0/token"
    OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting"

    # Token 缓存路径
    TOKEN_CACHE = "/tmp/baidu_ocr_token.json"

    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        max_retries: int = 2,
        timeout_seconds: int = 60,
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._access_token: Optional[str] = None

    # ── 接口属性 ──────────────────────────────────────

    @property
    def name(self) -> str:
        return "百度手写OCR + 规则引擎"

    @property
    def supports_bbox(self) -> bool:
        return True  # 百度 OCR 返回每行 location，支持 bbox

    # ── 验证 ──────────────────────────────────────────

    def validate(self) -> Tuple[bool, str]:
        if not self.api_key or not self.secret_key:
            return False, "百度 API Key / Secret Key 未配置。请设置环境变量 BAIDU_API_KEY 和 BAIDU_SECRET_KEY"
        return True, ""

    # ── 主入口 ────────────────────────────────────────

    def grade(self, grading_input: GradingInput) -> GradingResult:
        start_time = time.time()

        try:
            # Step 1: 获取 access_token
            access_token = self._get_access_token()

            # Step 2: 加载并编码图片
            image_b64 = self._load_and_encode_image(grading_input)

            # Step 3: 调用百度手写 OCR
            ocr_lines, full_text = self._call_handwriting_ocr(image_b64, access_token)

            # Step 4: 规则引擎批改
            from rule_engine import RuleEngine
            engine = RuleEngine()
            sentence_analyses = engine.grade(full_text)

            # Step 5: 将错误映射到 OCR 坐标
            self._map_errors_to_bbox(sentence_analyses, ocr_lines)

            # Step 6: 计算总分和总评
            total_deductions = sum(
                e.deduction_points
                for sa in sentence_analyses
                for e in sa.errors
            )
            total_score = max(0, min(100, 100 - total_deductions))
            overall_comment = self._generate_comment(total_score, sentence_analyses)

            # Step 7: 组装结果（含增强批改字段）
            enhanced = self._generate_enhanced_report(sentence_analyses, total_score, full_text)
            dim_scores = enhanced.get("dimension_scores", {})
            result = GradingResult(
                recognized_text=full_text,
                sentence_analyses=sentence_analyses,
                total_score=total_score,
                overall_comment=overall_comment,
                confidence=Confidence.MEDIUM,
                status=GradingStatus.SUCCESS,
                processing_time_ms=int((time.time() - start_time) * 1000),
                raw_response=json.dumps(
                    {"ocr_lines": [{"text": l.text, "bbox": l.bbox.to_list()} for l in ocr_lines]},
                    ensure_ascii=False, indent=2
                ),
                grader_name=self.name,
                homework_completion=enhanced.get("homework_completion", ""),
                strengths=enhanced.get("strengths", []),
                weaknesses=enhanced.get("weaknesses", []),
                suggestions=enhanced.get("suggestions", []),
                highlight_sentences=enhanced.get("highlight_sentences", []),
                parent_feedback=enhanced.get("parent_feedback", ""),
                system_tags=enhanced.get("system_tags", []),
                dimension_scores=dim_scores,
            )

            # 后处理
            result = self._post_process(result)

            return result

        except GradingException:
            raise
        except Exception as e:
            raise APIException(
                message=f"百度 OCR 批改异常: {str(e)}",
                grader_name=self.name,
                cause=e,
            )

    # ── 鉴权 ──────────────────────────────────────────

    def _get_access_token(self) -> str:
        """
        获取百度 OAuth 2.0 access_token。
        优先使用缓存（有效期30天），过期则重新获取。
        """
        # 尝试从缓存加载
        if os.path.exists(self.TOKEN_CACHE):
            try:
                with open(self.TOKEN_CACHE, "r") as f:
                    cache = json.load(f)
                if cache.get("expires_at", 0) > time.time():
                    return cache["access_token"]
            except Exception:
                pass

        # 重新获取
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        }

        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.AUTH_URL,
                    data=params,
                    timeout=self.timeout_seconds,
                )
                data = resp.json()

                if "access_token" in data:
                    token = data["access_token"]
                    expires_in = data.get("expires_in", 2592000)  # 默认30天
                    # 缓存
                    cache = {
                        "access_token": token,
                        "expires_at": time.time() + expires_in - 3600,  # 提前1小时过期
                    }
                    with open(self.TOKEN_CACHE, "w") as f:
                        json.dump(cache, f)
                    return token
                else:
                    error_desc = data.get("error_description", data.get("error", "未知错误"))
                    raise APIException(
                        message=f"百度鉴权失败: {error_desc}",
                        grader_name=self.name,
                    )
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise APIException(
                    message=f"百度鉴权请求失败: {str(e)}",
                    grader_name=self.name,
                    cause=e,
                )

        raise APIException(
            message="百度鉴权失败，已达最大重试次数",
            grader_name=self.name,
        )

    # ── 图片加载 ──────────────────────────────────────

    def _load_and_encode_image(self, inp: GradingInput) -> str:
        """加载图片并 Base64 编码，同时进行 URL encode"""
        if inp.image_data:
            img_bytes = inp.image_data
        else:
            with open(inp.image_path, "rb") as f:
                img_bytes = f.read()

        # 检查图片大小，如果超过 4MB 则压缩
        max_size = 4 * 1024 * 1024  # 百度限制 4MB base64 编码后
        if len(img_bytes) > max_size * 0.75:  # base64 膨胀约 1.33 倍
            # 压缩
            from io import BytesIO
            img = Image.open(BytesIO if inp.image_data else inp.image_path)
            if isinstance(img_bytes, bytes):
                from io import BytesIO
                img = Image.open(BytesIO(img_bytes))
            else:
                img = Image.open(inp.image_path)
            # 缩放到长边 2048
            w, h = img.size
            if max(w, h) > 2048:
                ratio = 2048 / max(w, h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            img_bytes = buf.getvalue()
            print(f"[百度OCR] 图片压缩: {len(img_bytes)} bytes (原图过大)")

        # Base64 编码 + URL encode（百度 API 要求）
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        encoded = urllib.parse.quote(b64)
        print(f"[百度OCR] 图片编码完成: base64长度={len(b64)}")
        return encoded

    # ── OCR 调用 ──────────────────────────────────────

    def _call_handwriting_ocr(self, image_b64_urlencoded: str, access_token: str) -> Tuple[List[OCRLine], str]:
        """
        调用百度手写文字识别 API。

        Args:
            image_b64_urlencoded: Base64 编码并 URL encode 后的图片数据
            access_token: 百度 OAuth access_token

        Returns:
            (OCRLine列表, 完整识别文本)
        """
        url = f"{self.OCR_URL}?access_token={access_token}"
        data = f"image={image_b64_urlencoded}"

        # 附加参数：检测涂改、返回置信度
        data += "&detect_alteration=true&probability=true"

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    data=data,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                result = resp.json()

                # 检查错误
                if "error_code" in result and result["error_code"] != 0:
                    error_msg = result.get("error_msg", "未知错误")
                    raise APIException(
                        message=f"百度 OCR 返回错误: [{result['error_code']}] {error_msg}",
                        grader_name=self.name,
                    )

                # 解析结果
                words_result = result.get("words_result", [])
                if not words_result:
                    raise ParseException(
                        message="百度 OCR 未识别到任何文字，请检查图片质量",
                        grader_name=self.name,
                    )

                ocr_lines = []
                full_text_parts = []

                for item in words_result:
                    words = item.get("words", "")
                    loc = item.get("location", {})
                    prob = item.get("probability", {})

                    bbox = BoundingBox(
                        x1=int(loc.get("left", 0)),
                        y1=int(loc.get("top", 0)),
                        x2=int(loc.get("left", 0) + loc.get("width", 0)),
                        y2=int(loc.get("top", 0) + loc.get("height", 0)),
                    )

                    ocr_lines.append(OCRLine(
                        text=words,
                        bbox=bbox,
                        confidence_avg=prob.get("average", 0.0),
                    ))

                    full_text_parts.append(words)

                filtered_lines = self._filter_body_ocr_lines(ocr_lines)
                full_text = "".join(line.text for line in filtered_lines)
                print(
                    f"[百度OCR] 识别完成: {len(ocr_lines)}行, "
                    f"正文过滤后 {len(filtered_lines)}行, {len(full_text)}字符"
                )
                print(f"[百度OCR] 正文文本: {full_text[:200]}...")

                return filtered_lines, full_text

            except (requests.exceptions.RequestException, ParseException) as e:
                if isinstance(e, ParseException):
                    raise
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise APIException(
                    message=f"百度 OCR 请求失败: {str(e)}",
                    grader_name=self.name,
                    cause=e,
                )

        raise APIException(
            message="百度 OCR 调用失败，已达最大重试次数",
            grader_name=self.name,
        )

    def _filter_body_ocr_lines(self, ocr_lines: List[OCRLine]) -> List[OCRLine]:
        """
        过滤作业模板、右侧教师点评、底部图例等非学生正文内容。

        目标是给规则引擎和 LLM 只喂学生译文，避免页眉与老师红字污染判断。
        """
        if not ocr_lines:
            return []

        noise_patterns = [
            r"姓名[:：]?",
            r"班级[:：]?",
            r"日期[:：]?",
            r"分数[:：]?",
            r"教师点评",
            r"老师点评",
            r"小石潭记$",
            r"需订正|好句|修改处",
            r"点睛句|建议译为|可改为|更完整|更通顺",
            r"二维码|扫码",
        ]
        noise_re = re.compile("|".join(noise_patterns))

        max_x = max((line.bbox.x2 for line in ocr_lines), default=0)
        first_body_idx = None
        body_start_re = re.compile(r"(从小丘|隔[着著]?竹林|听[到见]?水声|闻水声)")

        for idx, line in enumerate(ocr_lines):
            text = re.sub(r"\s+", "", line.text)
            if body_start_re.search(text):
                first_body_idx = idx
                break

        candidate_lines = ocr_lines[first_body_idx:] if first_body_idx is not None else ocr_lines
        filtered: List[OCRLine] = []

        for line in candidate_lines:
            text = re.sub(r"\s+", "", line.text)
            if not text:
                continue
            if noise_re.search(text):
                continue
            # 右侧教师点评一般从页面最右 25% 开始，且不是学生正文。
            if max_x and line.bbox.x1 > max_x * 0.72:
                continue
            filtered.append(line)

        return filtered or candidate_lines

    # ── 坐标映射 ──────────────────────────────────────

    def _map_errors_to_bbox(self, analyses: List[SentenceAnalysis], ocr_lines: List[OCRLine]):
        """
        将规则引擎检测到的错误文本映射到百度 OCR 的行坐标。

        策略：
        1. 对每个 ErrorItem，在 OCR 行中搜索其 original_text
        2. 精确匹配 → 直接用该行 bbox
        3. 子串匹配 → 找包含最多字符的 OCR 行
        4. 反向子串匹配 → line.text 在 error_text 中
        5. 逐字匹配 → 公共字符比例 > 0.3
        6. 句子级fallback → 用学生文本找最佳匹配行
        """
        for sa in analyses:
            # 先为句子本身找到最佳OCR行（用于fallback）
            sentence_bbox = None
            if sa.student_translation and sa.student_translation != "（未识别到此句翻译）":
                stu_clean = sa.student_translation.replace('，', '').replace('。', '').replace('☰', '')
                best_line = None
                best_score = 0
                for line in ocr_lines:
                    line_clean = line.text.replace('，', '').replace('。', '').replace('☰', '')
                    # 计算包含比例
                    if line_clean in stu_clean or stu_clean in line_clean:
                        score = len(line_clean) / max(len(stu_clean), 1)
                        if score > best_score:
                            best_score = score
                            best_line = line
                if best_line and best_score > 0.3:
                    sentence_bbox = best_line.bbox
                    sa.bbox = sentence_bbox

            for error in sa.errors:
                error_text = error.original_text
                if not error_text:
                    continue

                # 策略1：精确匹配
                best_line = None
                best_score = 0

                for line in ocr_lines:
                    if error_text == line.text:
                        best_line = line
                        best_score = 100
                        break

                # 策略2：子串匹配
                if best_score < 100:
                    for line in ocr_lines:
                        if error_text in line.text:
                            score = len(error_text) / len(line.text)
                            if score > best_score:
                                best_score = score
                                best_line = line

                # 策略3：反向子串匹配（line.text 在 error_text 中）
                if best_score == 0:
                    for line in ocr_lines:
                        if len(line.text) >= 2 and line.text in error_text:
                            score = len(line.text) / len(error_text)
                            if score > best_score:
                                best_score = score
                                best_line = line

                # 策略4：逐字匹配（降低阈值到0.3）
                if best_score == 0 and len(error_text) >= 2:
                    for line in ocr_lines:
                        common = sum(1 for c in error_text if c in line.text)
                        score = common / len(error_text)
                        if score > 0.3 and score > best_score:
                            best_score = score
                            best_line = line

                # 策略5：用句子级bbox作为fallback
                if best_line and best_score > 0:
                    error.bbox = best_line.bbox
                elif sentence_bbox:
                    error.bbox = sentence_bbox

    # ── 评语生成 ──────────────────────────────────────

    def _generate_comment(self, total_score: int, analyses: List[SentenceAnalysis]) -> str:
        """基于得分和错误分布生成总评"""
        total_errors = sum(len(sa.errors) for sa in analyses)
        error_types = {}
        for sa in analyses:
            for e in sa.errors:
                t = e.error_type.value
                error_types[t] = error_types.get(t, 0) + 1

        parts = []

        if total_score >= 90:
            parts.append("翻译整体准确，能较好地传达原文意思。")
        elif total_score >= 80:
            parts.append("翻译基本通顺，但存在一些关键词语误译和漏译问题。")
        elif total_score >= 60:
            parts.append("翻译存在较多错误，对文言实词和虚词的理解需要加强。")
        else:
            parts.append("翻译错误较多，建议对照标准译文逐句精读，重点掌握关键词汇的含义。")

        if error_types:
            type_str = "、".join(f"{k}{v}处" for k, v in sorted(error_types.items(), key=lambda x: -x[1]))
            parts.append(f"主要错误类型：{type_str}。")

        if total_score < 80:
            parts.append("建议：对照标准译文逐句精读，重点掌握实词（如'伐''清冽''下澈'等）的准确含义。")

        return "".join(parts)

    def _generate_enhanced_report(self, analyses: List[SentenceAnalysis], total_score: int, full_text: str) -> dict:
        """按《小石潭记批改要求》生成增强版批改报告"""
        from collections import Counter

        total_sentences = len(analyses)
        matched = sum(1 for sa in analyses if sa.student_translation and "未识别" not in sa.student_translation)
        all_errors = [e for sa in analyses for e in sa.errors]
        error_type_counts = Counter(e.error_type for e in all_errors)
        highlight_count = sum(1 for sa in analyses if sa.is_highlight)
        excellent_count = sum(1 for sa in analyses if sa.is_excellent)

        # 作业完成情况
        if matched == total_sentences:
            completion = f"已完成全文翻译（共{total_sentences}句），字迹通过OCR识别。"
        elif matched >= total_sentences * 0.7:
            completion = f"完成了大部分翻译（{matched}/{total_sentences}句），少量句子未识别。"
        elif matched >= total_sentences * 0.3:
            completion = f"完成了部分翻译（{matched}/{total_sentences}句），存在明显漏段。"
        else:
            completion = f"仅完成少量翻译（{matched}/{total_sentences}句），后半篇未见译文。"

        # 多维评分
        completeness = min(20, int((matched / total_sentences) * 20)) if total_sentences > 0 else 0
        content_errors = error_type_counts.get(ErrorType.CONTENT_ERROR, 0)
        accuracy = max(0, min(20, 20 - content_errors * 2))
        keyword_errors = sum(1 for e in all_errors if e.deduction_points >= 5)
        keyword_mastery = max(0, min(20, 20 - keyword_errors * 3))
        omission_errors = error_type_counts.get(ErrorType.OMISSION, 0)
        fidelity = max(0, min(20, 20 - omission_errors * 3))
        fluency = min(20, 12 + excellent_count * 2)
        structure = min(20, 14 + (0 if content_errors > 3 else 4))

        dimension_scores = {
            "完整度": completeness,
            "准确度": accuracy,
            "重点词掌握": keyword_mastery,
            "句式处理": structure,
            "表达流畅度": fluency,
            "忠实原文": fidelity,
        }

        # 优点
        strengths = []
        if excellent_count >= 2:
            strengths.append(f"共有{excellent_count}句翻译准确流畅，表达清晰自然。")
        if highlight_count >= 3:
            strengths.append(f"已识别{highlight_count}句点睛句，关键内容掌握较好。")
        if matched >= total_sentences * 0.8:
            strengths.append("作业完成度较高，全文翻译基本完整。")
        if not strengths:
            strengths.append("能尝试翻译文言文，态度认真。")

        # 问题
        weaknesses = []
        if content_errors > 2:
            weaknesses.append(f"实词理解薄弱，{content_errors}处关键词翻译不准确。")
        if omission_errors > 2:
            weaknesses.append(f"存在{omission_errors}处漏译，部分句子关键内容缺失。")
        if matched < total_sentences * 0.6:
            weaknesses.append("翻译不完整，后半篇未见译文。")
        if not weaknesses:
            weaknesses.append("个别词句还需进一步推敲。")

        # 建议
        suggestions = [
            "翻译时先逐字找对应，再组织现代汉语表达。",
            "重点字词（如'可''许''清''去''以为'等易错词）建议整理到笔记本。",
        ]
        if highlight_count < 3:
            suggestions.append("建议熟读或背诵点睛句，加深对文章结构和情感的理解。")
        if matched < total_sentences * 0.6:
            suggestions.append("需要补全全文翻译后再次提交。")

        # 点睛句积累
        highlight_sentences = [
            {"classical": sa.original_classical, "translation": sa.student_translation[:50],
             "comment": sa.highlight_comment}
            for sa in analyses if sa.is_highlight
        ]

        # 系统标签
        tags = []
        if content_errors > 2:
            tags.append("实词薄弱")
        if omission_errors > 2:
            tags.append("有漏译")
        if error_type_counts.get(ErrorType.ADDITION, 0) > 0:
            tags.append("扩写过度")
        if matched < total_sentences * 0.6:
            tags.append("翻译不完整")
        if excellent_count >= 3:
            tags.append("完成优秀")
        if highlight_count >= 3:
            tags.append("点睛句掌握好")

        # 家长反馈
        if total_score >= 80:
            parent_feedback = (
                f"《小石潭记》作业完成得不错！全文翻译基本准确，重点字词如'空游无所依''斗折蛇行'等处理得较好。"
                f"建议孩子把老师标注的点睛句整理到笔记本上，后续可以熟读甚至背诵，对初中学习和考试都很有帮助。"
            )
        elif total_score >= 60:
            parent_feedback = (
                f"《小石潭记》作业整体翻译方向是对的，说明孩子对原文大意有一定理解。"
                f"这次主要要注意个别词句不要漏译，文言文翻译讲究字字落实。"
                f"建议孩子把标注的地方整理到笔记本上，下次翻译会更准确。"
            )
        else:
            parent_feedback = (
                f"《小石潭记》是中考重点篇目，这次作业目前完成度还不够。"
                f"建议先补全文翻译，再重点整理'潭中鱼可百许头''斗折蛇行''凄神寒骨'等重点句。"
                f"孩子交几次作业后就能熟悉批改习惯，有问题可以及时问老师。"
            )

        return {
            "homework_completion": completion,
            "strengths": strengths[:4],
            "weaknesses": weaknesses[:4],
            "suggestions": suggestions[:3],
            "highlight_sentences": highlight_sentences[:5],
            "parent_feedback": parent_feedback,
            "system_tags": tags,
            "dimension_scores": dimension_scores,
        }

    # ── 后处理 ────────────────────────────────────────

    def _post_process(self, result: GradingResult) -> GradingResult:
        """结果校验和调整"""
        result.normalize_scores()

        # 错误数检查
        if result.total_errors == 0 and result.total_score < 90:
            result.status = GradingStatus.LOW_CONFIDENCE
            result.error_message = "未检测到明显错误但得分较低，可能是 OCR 识别不完整导致"

        # 识别文本检查
        if len(result.recognized_text) < 10:
            result.status = GradingStatus.IMAGE_POOR
            result.error_message = "OCR 识别文本过短，图片可能模糊或不包含手写文字"

        return result
