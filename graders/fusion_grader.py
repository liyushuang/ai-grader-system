"""
融合批改器 — 百度OCR + 规则引擎预处理 + Qwen-VL-Max 终判

三层融合架构：
1. 百度OCR：精确识别学生手写文字 + 获取行坐标
2. 规则引擎：句子匹配 + 语义等价初判 + 标记待确认项
3. Qwen-VL-Max：基于标准译文 + 初判结果做最终判断
4. 融合：LLM结果 + OCR行坐标 → 精确标注

这是长期最优方案，兼具 OCR 的精确坐标和 LLM 的语义理解能力。
"""

import json
import time
import base64
import io
import re
from typing import List, Optional, Tuple

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from grader_base import (
    GradingStrategy, GradingInput, GradingResult,
    SentenceAnalysis, ErrorItem, BoundingBox,
    ErrorType, Confidence, GradingStatus,
    GradingException, APIException, ParseException,
    Annotation, AnnotationType, AnnotationSource,
)


class FusionGrader(GradingStrategy):
    """
    融合批改器：百度OCR → 规则引擎预处理 → Qwen-VL-Max终判

    优势：
    - OCR行坐标精确（比LLM Grounding更稳定）
    - 规则引擎做初筛，减少LLM认知负担
    - LLM做终判，利用语义理解解决规则死板问题
    - 精确参照注入，评分有据可依
    """

    def __init__(
        self,
        dashscope_api_key: str = None,
        baidu_api_key: str = None,
        baidu_secret_key: str = None,
        volcano_api_key: str = None,
        llm_provider: str = "qwen",
        model: str = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        self.dashscope_api_key = dashscope_api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.baidu_api_key = baidu_api_key or os.environ.get("BAIDU_API_KEY", "")
        self.baidu_secret_key = baidu_secret_key or os.environ.get("BAIDU_SECRET_KEY", "")
        self.volcano_api_key = volcano_api_key or os.environ.get("VOLCANO_API_KEY", "")
        self.llm_provider = llm_provider.lower()
        self.temperature = temperature
        self.max_tokens = max_tokens
        if self.llm_provider == "volcano":
            self.model = model or "doubao-1-5-vision-pro-32k-250115"
        else:
            self.model = model or "qwen-max"

    @property
    def name(self) -> str:
        if self.llm_provider == "volcano":
            return f"Fusion (百度OCR + 规则引擎 + 火山引擎 {self.model})"
        return f"Fusion (百度OCR + 规则引擎 + Qwen {self.model})"

    @property
    def supports_bbox(self) -> bool:
        return True

    def validate(self) -> Tuple[bool, str]:
        if not self.baidu_api_key:
            self.baidu_api_key = os.environ.get("BAIDU_API_KEY", "")
        if not self.baidu_secret_key:
            self.baidu_secret_key = os.environ.get("BAIDU_SECRET_KEY", "")
        if not self.baidu_api_key or not self.baidu_secret_key:
            return False, "百度OCR API Key未配置"

        if self.llm_provider == "volcano":
            if not self.volcano_api_key:
                self.volcano_api_key = os.environ.get("VOLCANO_API_KEY", "")
            if not self.volcano_api_key:
                return False, "Volcano Ark API Key未配置"
        else:
            if not self.dashscope_api_key:
                self.dashscope_api_key = os.environ.get("DASHSCOPE_API_KEY", "")
            if not self.dashscope_api_key:
                return False, "DashScope API Key未配置"

        return True, ""

    def grade(self, grading_input: GradingInput) -> GradingResult:
        start_time = time.time()

        try:
            # ── Phase 1: 百度OCR识别 ──
            print("[Fusion] Phase 1: 百度OCR识别...")
            ocr_lines, full_text = self._run_baidu_ocr(grading_input)

            # ── Phase 2: 规则引擎预处理 ──
            print("[Fusion] Phase 2: 规则引擎预处理...")
            from rule_engine import RuleEngine
            engine = RuleEngine()
            sentence_analyses = engine.grade(full_text)

            # 映射OCR坐标
            self._map_ocr_coords(sentence_analyses, ocr_lines, full_text)

            # ── Phase 3: 构建预处理摘要 ──
            print("[Fusion] Phase 3: 构建LLM提示...")
            pre_judgment = self._build_pre_judgment(sentence_analyses)

            # ── Phase 4: LLM终判 ──
            print(f"[Fusion] Phase 4: {self.llm_provider.upper()} 终判...")
            llm_result = self._run_llm_final(
                grading_input, full_text, pre_judgment
            )

            # ── Phase 5: 融合坐标 ──
            print("[Fusion] Phase 5: 融合坐标...")
            result = self._fuse_results(
                sentence_analyses, ocr_lines, llm_result,
                grading_input, start_time,
            )

            return result

        except Exception as e:
            print(f"[Fusion] 批改异常: {e}")
            import traceback
            traceback.print_exc()
            return GradingResult(
                recognized_text="",
                total_score=0,
                overall_comment=f"批改异常: {str(e)}",
                status=GradingStatus.PROCESSING_ERROR,
                error_message=str(e),
                grader_name=self.name,
            )

    def grade_stream(self, grading_input: GradingInput):
        """流式批改：逐阶段推送进度"""
        start_time = time.time()

        try:
            # ── Phase 1: 百度OCR识别 ──
            yield {"type": "stage", "stage": "ocr", "message": "🔍 正在识别手写文字..."}
            ocr_lines, full_text = self._run_baidu_ocr(grading_input)
            yield {"type": "stage", "stage": "ocr_done",
                   "message": f"✅ OCR完成：识别到 {len(ocr_lines)} 行文字"}

            # ── Phase 2: 规则引擎预处理 ──
            yield {"type": "stage", "stage": "rule", "message": "📐 规则引擎初判中..."}
            from rule_engine import RuleEngine
            engine = RuleEngine()
            sentence_analyses = engine.grade(full_text)
            self._map_ocr_coords(sentence_analyses, ocr_lines, full_text)
            yield {"type": "stage", "stage": "rule_done",
                   "message": f"✅ 规则初判：{len(sentence_analyses)} 句，"
                             f"{sum(len(sa.errors) for sa in sentence_analyses)} 处错误"}

            # ── Phase 3: 构建预处理摘要 ──
            pre_judgment = self._build_pre_judgment(sentence_analyses)

            # ── Phase 4: Qwen-VL-Max终判（流式）──
            yield {"type": "stage", "stage": "llm", "message": "🧠 AI 正在分析..."}
            system_prompt = self._build_fusion_system_prompt(
                grading_input, full_text, pre_judgment
            )

            # 流式调用 LLM
            llm_buffer = ""
            for chunk in self._run_llm_stream(grading_input, system_prompt):
                if chunk:
                    llm_buffer += chunk
                    yield {"type": "llm_chunk", "text": chunk}

            # 解析 LLM 结果
            if self.llm_provider == "volcano":
                from volcano_grader import VolcanoGrader
                llm = VolcanoGrader(api_key=self.volcano_api_key)
            else:
                from qwen_vl_max_grader import QwenVLMaxGrader
                llm = QwenVLMaxGrader(api_key=self.dashscope_api_key)
            llm_result = llm._parse_response(llm_buffer, grading_input)
            yield {"type": "stage", "stage": "llm_done",
                   "message": f"✅ AI 分析完成：{llm_result.total_score}分，"
                             f"{llm_result.total_errors} 处错误"}

            # ── Phase 5: 融合坐标 ──
            yield {"type": "stage", "stage": "fuse", "message": "🔗 正在融合标注坐标..."}
            result = self._fuse_results(
                sentence_analyses, ocr_lines, llm_result,
                grading_input, start_time,
            )
            yield {"type": "stage", "stage": "fuse_done",
                   "message": f"✅ 标注就绪：{sum(len(sa.errors) for sa in result.sentence_analyses)} 处错误，"
                             f"{sum(1 for sa in result.sentence_analyses if sa.is_excellent)} 个精彩句，"
                             f"{sum(1 for sa in result.sentence_analyses if sa.is_highlight)} 个点睛句"}

            # 生成标注
            from utils.annotation_utils import generate_annotations_from_result, annotations_to_dict_list
            annotations = generate_annotations_from_result(result)

            # 返回最终结果
            yield {"type": "result", "data": {
                "total_score": result.total_score,
                "total_errors": result.total_errors,
                "overall_comment": result.overall_comment,
                "homework_completion": result.homework_completion,
                "dimension_scores": result.dimension_scores,
                "dimension_analysis": getattr(result, 'dimension_analysis', {}),
                "strengths": result.strengths,
                "weaknesses": result.weaknesses,
                "suggestions": result.suggestions,
                "highlight_sentences": result.highlight_sentences,
                "parent_feedback": result.parent_feedback,
                "system_tags": result.system_tags,
                "grader_name": result.grader_name,
                "processing_time_ms": result.processing_time_ms,
                "annotations": annotations_to_dict_list(annotations),
            }}

        except Exception as e:
            yield {"type": "error", "message": f"批改异常: {str(e)}"}

    # ── Phase 1: OCR ──────────────────────────────

    def _run_baidu_ocr(self, inp: GradingInput) -> Tuple[list, str]:
        """调用百度手写OCR识别"""
        from baidu_ocr_grader import BaiduOCRGrader

        baidu = BaiduOCRGrader(
            api_key=self.baidu_api_key,
            secret_key=self.baidu_secret_key,
        )

        # 获取access_token
        access_token = baidu._get_access_token()

        # 加载并编码图片
        image_b64 = baidu._load_and_encode_image(inp)

        # 调用OCR
        return baidu._call_handwriting_ocr(image_b64, access_token)

    # ── Phase 2: OCR坐标映射 ──────────────────────

    def _map_ocr_coords(self, analyses: List[SentenceAnalysis],
                         ocr_lines: list, full_text: str):
        """将错误映射到OCR行坐标，同时设置句子级bbox"""
        from baidu_ocr_grader import BaiduOCRGrader

        # 创建临时grader来复用坐标映射逻辑
        baidu = BaiduOCRGrader(
            api_key=self.baidu_api_key,
            secret_key=self.baidu_secret_key,
        )
        baidu._map_errors_to_bbox(analyses, ocr_lines)

        # 为每个句子设置bbox（基于匹配到的OCR行范围）
        for sa in analyses:
            if not sa.student_translation or sa.student_translation.startswith("（未识别"):
                continue
            sa.bbox = self._find_sentence_bbox(sa.student_translation, ocr_lines)

    def _find_sentence_bbox(self, student_text: str, ocr_lines: list) -> Optional[BoundingBox]:
        """在OCR行中搜索学生文本对应的精确行范围"""
        clean_text = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', student_text)

        # 按顺序找到首尾匹配行（更精确的边界）
        first_match = None
        last_match = None
        matched_indices = []

        for i, line in enumerate(ocr_lines):
            line_clean = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', line.text)
            common = sum(1 for c in line_clean if c in clean_text)
            if common >= max(2, min(3, len(line_clean) // 3)):
                matched_indices.append(i)
                if first_match is None:
                    first_match = line
                last_match = line

        if not matched_indices:
            return None

        # 仅用连续的行（跳过孤立的误匹配行）
        if len(matched_indices) > 2:
            # 找最大的连续区间
            best_start = matched_indices[0]
            best_end = matched_indices[0]
            current_start = matched_indices[0]

            for j in range(1, len(matched_indices)):
                if matched_indices[j] - matched_indices[j-1] <= 2:
                    # 连续（允许间隔1行）
                    if matched_indices[j] - current_start > best_end - best_start:
                        best_start = current_start
                        best_end = matched_indices[j]
                else:
                    current_start = matched_indices[j]

            first_match = ocr_lines[best_start]
            last_match = ocr_lines[best_end]

        return BoundingBox(
            first_match.bbox.x1,
            first_match.bbox.y1,
            last_match.bbox.x2,
            last_match.bbox.y2,
        )

    # ── Phase 3: 预处理摘要 ──────────────────────

    def _build_pre_judgment(self, analyses: List[SentenceAnalysis]) -> str:
        """构建预处理摘要，供LLM参考"""
        lines = ["## 规则引擎预处理结果（供参考，以图片实际内容为准）"]
        for i, sa in enumerate(analyses, 1):
            status = []
            if sa.errors:
                status.append(f"发现 {len(sa.errors)} 个错误")
            if sa.is_excellent:
                status.append("翻译优秀")
            if not status:
                status.append("无明显错误")
            lines.append(f"{i}. {sa.original_classical} → {sa.student_translation} ({', '.join(status)})")
        return "\n".join(lines)

    def _build_fusion_system_prompt(self, inp: GradingInput, ocr_text: str,
                                     pre_judgment: str) -> str:
        """构建融合批改的System Prompt（基于《小石潭记批改要求》文档优化版）"""
        from qwen_vl_max_grader import QwenVLMaxGrader

        sentence_pairs = QwenVLMaxGrader._default_sentence_pairs()

        return f"""你是资深中学语文教师，拥有20年文言文教学经验，专门批改《小石潭记》翻译作业。批改核心目标：字字落实、句句对应、忠于原文、语句通顺、理解文章。

## 批改课文：《{inp.textbook_name}》（{inp.textbook_author}）

## 逐句精确参照（必须逐句严格对照）
{sentence_pairs}

## 百度OCR识别文本（参考，以图片实际内容为准）
{ocr_text}

{pre_judgment}

## 一、重点字词批改要求（必须逐字检查）

### 1. 一词多义
- 可："潭中鱼可百许头"译为"大约"；"明灭可见"译为"可以"
- 许："百许头"表示约数，译为"来"
- 环："如鸣珮环"译为"玉饰"；"四面竹树环合"译为"环绕"
- 出："卷石底以出"译为"露出水面"
- 游："皆若空游无所依"译为"游动"；"似与游者相乐"译为"游玩的人"

### 2. 古今异义（必须译出古义，按今义理解算错译）
- 小生：古义"年轻人"，不能译成"学生""小孩"
- 去：古义"离开"，不能译成"前往"
- 可："可百许头"古义"大约"，不能译成"可以"
- 以为：古义"把……作为"，不能译成"认为"

### 3. 词类活用（必须译出活用含义）
- 西："从小丘西行"译为"向西"
- 下："下见小潭"译为"向下"
- 空："皆若空游"译为"在空中"
- 西南："潭西南而望"译为"向西南"
- 斗、蛇："斗折蛇行"译为"像北斗星那样曲折，像蛇那样蜿蜒前行"
- 犬牙："犬牙差互"译为"像狗的牙齿那样参差交错"
- 凄、寒："凄神寒骨"译为"使人心神凄凉、寒气透骨"
- 乐："心乐之"译为"以……为乐"或"心里为此感到高兴"

### 4. 特殊句式
- "全石以为底"：宾语前置，即"以全石为底"，译为"小潭以整块石头为底"
- "斗折蛇行"：省略"溪水"，译为"溪水像北斗星那样曲折，像蛇那样蜿蜒前行"
- "坐潭上"：省略"我、于"，译为"我坐在小石潭边"

## 二、常见问题类型与判断标准

### 1. 漏译（扣2分/处）
- 原文有对应内容，学生译文没有体现
- 重点词、关键句、情感词没有翻译
- 常见漏译："心乐之"、"尤""冽"、"可""许"、"佁然""俶尔""翕忽"、"凄神寒骨""悄怆幽邃"

### 2. 错译（扣3-5分/处）
- 重点词语含义错误
- 词类活用未译出
- 古今异义按现代义理解
- 常见错译："可"译成"可以"、"许"漏掉约数、"清"在"其境过清"中译成"清澈"、"去"译成"前往"、"小生"译成"小学生"、"全石以为底"译成"全是石头"、"斗折蛇行"只译成"弯弯曲曲"

### 3. 扩写过度（扣1-2分/处）
- 加入原文没有的信息
- 把翻译写成想象作文或景物描写
- 增加人物心理、景物细节、作者评价等原文没有的内容
- 允许适度补足现代汉语语序和必要主语，但不能改变原文意思

### 4. 主语缺失（扣2分/处）
- 原文省略主语，学生翻译时没有补出，导致现代汉语不完整
- 常见："下见小潭"应补"我向下看见"、"潭西南而望"应补"向小石潭的西南方望去"、"坐潭上"应补"我坐在小石潭边"

## 三、点睛句库（每次批改至少选3句标注）

1. "从小丘西行百二十步，隔篁竹，闻水声，如鸣珮环，心乐之" — 发现小潭与情感起点
2. "全石以为底，近岸，卷石底以出，为坻，为屿，为嵁，为岩" — 石底奇观
3. "青树翠蔓，蒙络摇缀，参差披拂" — 青树翠蔓
4. "潭中鱼可百许头，皆若空游无所依" — 空游无所依（侧面写水清）
5. "日光下澈，影布石上。佁然不动，俶尔远逝，往来翕忽，似与游者相乐" — 鱼影与游鱼
6. "潭西南而望，斗折蛇行，明灭可见。其岸势犬牙差互，不可知其源" — 溪流蜿蜒
7. "坐潭上，四面竹树环合，寂寥无人，凄神寒骨，悄怆幽邃" — 由乐转忧（情感核心）
8. "以其境过清，不可久居，乃记之而去" — 离潭原因

## 四、标注规则（严格控制数量，避免过度拥挤）

### 标注类型
- is_excellent=true：翻译准确流畅、用词精彩的句子 → 波浪线标注（至少2处，最多4处）
- errors非空：有翻译错误的句子 → 横线标注（重点标2-5处，必须具体到错误词）
  - error_type 必须用：实词错误/虚词错误/漏译/多译/错别字/语序不当/主语缺失/扩写过度
  - original_text 必须写具体的错误原文（如"砍倒"不是整句）
  - correct_text 必须写正确翻译
  - reason 必须写清楚错误原因（如"'可'应译为'大约'，学生译成'可以'属于古今异义错误"）
- is_highlight=true：点睛句 → 星星标注（至少3句）

### 标注数量控制
- 波浪线优秀句：至少2处
- 横线问题句：2-5处，重点标影响得分的重点词误译
- 点睛句：至少3句
- 总评：1段
- 建议：1-3条

## 五、语义等价宽容（以下情况不扣分）
- "铺满石头为底" ≈ "以整块石头为底"
- "心中很是快乐" ≈ "心里很高兴"
- "没有任何东西靠着" ≈ "没有依托"
- "听闻水的声音" ≈ "听到了水声"
- 核心语义一致，用词差异不扣分

## 六、评分维度（各0-20分，必须差异化）
| 维度 | 满分标准 | 常见扣分原因 |
|------|---------|-------------|
| 完整度 | 实际翻译句子数/11 × 20 | 漏句不译、后半篇未完成 |
| 准确度 | 关键词翻译准确程度 | 实词错、虚词错、古今异义错误 |
| 重点词掌握 | 重点实词虚词掌握 | 重点词错译、漏译 |
| 句式处理 | 文言特殊句式处理 | 语序不当、主语缺失 |
| 表达流畅度 | 现代汉语表达通顺 | 生硬直译、口语化 |
| 忠实原文 | 无随意增删 | 多译、扩写过度 |

## 七、总评要求
- overall_comment：100-150字，先肯定优点再指出问题，有教学指导意义，必须具体指出句子问题
- strengths：2-4个具体优点（字迹工整、重点句准确、译文通顺、有画面感等）
- weaknesses：1-4个具体问题（漏译、重点词不准、句式未处理好、扩写过度、主语缺失等）
- suggestions：1-3条具体可操作建议（逐字找对应、重点词整理到错题本、点睛句背诵等）
- parent_feedback：面向家长的反馈，50-80字，说明批改符号含义（波浪线=表扬，横线=需订正）
- system_tags：2-5个标签

## 八、维度详细分析（dimension_analysis，每个维度必须写分析）
{{
  "完整度": {{"strength":"例如：11句中翻译了10句，整体完成度较高","weakness":"例如：缺少'俶尔远逝'的翻译，可补充"}},
  "准确度": {{"strength":"例如：'全石以为底'翻译准确","weakness":"例如：'犬牙差互'翻译有偏差"}},
  "重点词掌握": {{"strength":"例如：'可…许''澈'等虚词翻译得当","weakness":"例如：'伐'译为'攻打'不够准确，应为'砍伐'"}},
  "句式处理": {{"strength":"例如：省略句补充得当","weakness":"例如：倒装句处理可以更自然"}},
  "表达流畅度": {{"strength":"例如：整体表达通顺，阅读流畅","weakness":"例如：部分语句偏直译，可更贴近现代汉语表达"}},
  "忠实原文": {{"strength":"例如：基本没有随意添加内容","weakness":"例如：'明灭可见'的翻译略有增译"}}
}}

## 输出纯JSON（勿加```json标记，严格按照格式）
{{
  "recognized_text": "学生完整手写译文",
  "sentence_analysis": [
    {{
      "original_classical": "原文",
      "student_translation": "翻译",
      "standard_translation": "标准译文",
      "errors": [{{"error_type":"实词错误","original_text":"错误原文（必须具体到词，不能写整句）","correct_text":"正确翻译","reason":"错误说明（必须指出具体错误类型，如古今异义/词类活用/漏译等）","deduction_points":3}}],
      "sentence_score": N,
      "is_excellent": false,
      "is_highlight": false,
      "highlight_comment": ""
    }}
  ],
  "total_score": N,
  "overall_comment": "100-150字总评，先肯定优点再指出问题，必须具体",
  "dimension_scores": {{"完整度":N,"准确度":N,"重点词掌握":N,"句式处理":N,"表达流畅度":N,"忠实原文":N}},
  "dimension_analysis": {{"完整度":{{"strength":"...","weakness":"..."}},"准确度":{{"strength":"...","weakness":"..."}},"重点词掌握":{{"strength":"...","weakness":"..."}},"句式处理":{{"strength":"...","weakness":"..."}},"表达流畅度":{{"strength":"...","weakness":"..."}},"忠实原文":{{"strength":"...","weakness":"..."}}}},
  "homework_completion": "描述翻译了哪些句子，是否完成全文",
  "strengths": ["具体优点"], "weaknesses": ["具体问题"], "suggestions": ["可操作建议"],
  "highlight_sentences": ["点睛句原文"],
  "parent_feedback": "家长反馈50-80字，说明批改符号含义", "system_tags": ["标签"],
  "confidence": "高"
}}"""

    # ── Phase 4: LLM终判 ─────────────────────────

    def _run_llm_final(self, inp: GradingInput, ocr_text: str,
                       pre_judgment: str) -> GradingResult:
        """调用 LLM 进行终判（支持 Qwen 和 Volcano）"""
        system_prompt = self._build_fusion_system_prompt(inp, ocr_text, pre_judgment)

        if self.llm_provider == "volcano":
            from volcano_grader import VolcanoGrader
            volcano = VolcanoGrader(
                api_key=self.volcano_api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return volcano._call_api(inp, system_prompt)
        else:
            from qwen_vl_max_grader import QwenVLMaxGrader
            qwen = QwenVLMaxGrader(
                api_key=self.dashscope_api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return qwen._call_api(inp, system_prompt)

    def _run_llm_stream(self, inp: GradingInput, system_prompt: str):
        """流式调用 LLM，逐 token 返回纯文本字符串（支持 Qwen 和 Volcano）"""
        if self.llm_provider == "volcano":
            from volcano_grader import VolcanoGrader
            volcano = VolcanoGrader(
                api_key=self.volcano_api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            image_b64, _ = volcano._load_and_encode_image(inp)
            user_content = [
                {
                    "type": "text",
                    "text": f"请批改以下学生提交的《{inp.textbook_name}》文言文翻译作业。仔细识别图片中的手写文字，与标准译文逐句对照，找出所有错误并标注位置。"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                        "detail": "high"
                    }
                }
            ]
            for event in volcano._call_api_stream(system_prompt, user_content):
                if event.get("type") == "llm_chunk":
                    yield event["text"]
                elif event.get("type") == "llm_error":
                    raise Exception(event.get("message", "LLM API 调用失败"))
        else:
            from qwen_vl_max_grader import QwenVLMaxGrader
            qwen = QwenVLMaxGrader(
                api_key=self.dashscope_api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            image_b64, _ = qwen._load_and_encode_image(inp)
            user_content = [
                {
                    "type": "text",
                    "text": f"请批改以下学生提交的《{inp.textbook_name}》文言文翻译作业。仔细识别图片中的手写文字，与标准译文逐句对照，找出所有错误并标注位置。"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                        "detail": "high"
                    }
                }
            ]
            for event in qwen._call_api_stream(system_prompt, user_content):
                if event.get("type") == "llm_chunk":
                    yield event["text"]
                elif event.get("type") == "llm_error":
                    raise Exception(event.get("message", "LLM API 调用失败"))
            # llm_done、llm_retry 等事件忽略，由外部根据 buffer 判断完成

    # ── Phase 5: 融合结果 ─────────────────────────

    def _fuse_results(self, rule_analyses: List[SentenceAnalysis],
                       ocr_lines: list, llm_result: GradingResult,
                       inp: GradingInput, start_time: float) -> GradingResult:
        """
        融合：LLM语义判断 + 规则引擎精确OCR坐标

        策略：
        1. 句子级 bbox：优先用规则引擎的精确坐标（基于OCR行范围），
           规则引擎没有则用字符匹配
        2. 错误级 bbox：LLM错误 → 在规则引擎错误中找同名 → 复用精确坐标
           找不到 → 在OCR行中做字符位置匹配
        3. 精彩句/点睛句：用句子级 bbox（波浪线/星星标注在整句范围）
        """
        # 构建规则引擎的坐标索引：{student_translation_hash: (sentence_bbox, {error_text: bbox})}
        rule_index = {}
        for rsa in rule_analyses:
            if rsa.student_translation and not rsa.student_translation.startswith("（未"):
                err_map = {}
                for e in rsa.errors:
                    if e.original_text and e.bbox:
                        err_map[e.original_text] = e.bbox
                rule_index[rsa.student_translation] = (rsa.bbox, err_map)

        total_mapped = 0
        total_errors_mapped = 0

        for sa in llm_result.sentence_analyses:
            stu_text = sa.student_translation

            # ── 句子级 bbox：优先从规则引擎获取精确坐标 ──
            if not sa.bbox and stu_text and not stu_text.startswith("（未"):
                # 策略1：在规则引擎索引中精确匹配
                if stu_text in rule_index:
                    sa.bbox = rule_index[stu_text][0]
                    total_mapped += 1
                else:
                    # 策略2：模糊匹配
                    best_bbox = None
                    best_score = 0
                    for rule_text, (rule_bbox, _) in rule_index.items():
                        if rule_text in stu_text or stu_text in rule_text:
                            score = len(set(rule_text) & set(stu_text)) / max(len(stu_text), 1)
                            if score > best_score:
                                best_score = score
                                best_bbox = rule_bbox
                    if best_bbox and best_score > 0.5:
                        sa.bbox = best_bbox
                        total_mapped += 1
                    else:
                        # 策略3：OCR行字符匹配
                        sa.bbox = self._find_sentence_bbox(stu_text, ocr_lines)
                        if sa.bbox:
                            total_mapped += 1

            # ── 错误级 bbox：优先从规则引擎复用精确坐标 ──
            for error in sa.errors:
                if error.bbox:
                    total_errors_mapped += 1
                    continue

                err_text = error.original_text
                if not err_text:
                    # 无错误文本，用句子级 bbox
                    if sa.bbox:
                        error.bbox = sa.bbox
                        total_errors_mapped += 1
                    continue

                # 策略1：在规则引擎索引中精确匹配错误文本
                found = False
                for rule_text, (_, err_map) in rule_index.items():
                    if err_text in err_map:
                        error.bbox = err_map[err_text]
                        total_errors_mapped += 1
                        found = True
                        break

                if found:
                    continue

                # 策略2：在OCR行中做字符位置精确定位
                error_bbox = self._find_error_in_ocr_lines(err_text, ocr_lines, sa.student_translation)
                if error_bbox:
                    error.bbox = error_bbox
                    total_errors_mapped += 1
                elif sa.bbox:
                    # 策略3：句子级 fallback
                    error.bbox = sa.bbox
                    total_errors_mapped += 1

        print(f"[Fusion] 坐标映射: {total_mapped} 句, {total_errors_mapped} 个错误")
        print(f"[Fusion] sentence_analyses: {len(llm_result.sentence_analyses)} 句, "
              f"总错误: {sum(len(sa.errors) for sa in llm_result.sentence_analyses)}")

        llm_result.grader_name = self.name
        llm_result.processing_time_ms = int((time.time() - start_time) * 1000)
        return llm_result

    def _find_error_in_ocr_lines(self, err_text: str, ocr_lines: list,
                                   sentence_text: str = "") -> Optional[BoundingBox]:
        """
        在OCR行中精确定位错误文本的位置。

        改进策略：
        1. 先用 sentence_text 找到对应的 OCR 行（解决 OCR 和 LLM 文本不一致问题）
        2. 在找到的 OCR 行内定位 err_text 的位置
        3. 如果 err_text 找不到，尝试用相似度匹配
        4. 如果都找不到，返回句子级 bbox
        """
        if not err_text:
            return None

        clean_err = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', err_text)
        clean_sentence = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', sentence_text) if sentence_text else ""

        # 策略1：先用 sentence_text 找到最匹配的 OCR 行
        best_line = None
        best_line_score = 0
        
        for line in ocr_lines:
            line_clean = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', line.text)
            # 计算句子相似度
            if clean_sentence:
                common = sum(1 for c in clean_sentence if c in line_clean)
                score = common / max(len(clean_sentence), 1)
                if score > best_line_score:
                    best_line_score = score
                    best_line = line
            # 同时检查 err_text 是否在该行中
            if clean_err in line_clean:
                # 如果 err_text 直接匹配，优先使用这一行
                best_line = line
                best_line_score = 1.0
                break

        if not best_line or best_line_score < 0.3:
            # 尝试逐字匹配
            for line in ocr_lines:
                line_clean = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', line.text)
                common = sum(1 for c in clean_err if c in line_clean)
                score = common / max(len(clean_err), 1)
                if score > 0.5:
                    best_line = line
                    break

        if not best_line:
            # 最后的 fallback：如果 sentence 匹配到了某行，就用那行
            if best_line_score > 0 and best_line:
                return self._narrow_bbox_to_text(clean_err, best_line)
            # 如果 err_text 的第一个字在某行中，返回那行
            if clean_err:
                first_char = clean_err[0]
                for line in ocr_lines:
                    if first_char in line.text:
                        return self._narrow_bbox_to_text(clean_err, line)
            # 最后的最后：返回第一行
            if ocr_lines:
                return self._narrow_bbox_to_text(clean_err, ocr_lines[0])
            return None

        # 策略2：在找到的 OCR 行内精确定位 err_text
        return self._narrow_bbox_to_text(clean_err, best_line)

    def _narrow_bbox_to_text(self, text: str, ocr_line) -> BoundingBox:
        """
        将 bbox 缩小到行内特定文字的位置。
        
        改进：使用更精确的字符定位，考虑中文字符宽度。
        """
        line_text = ocr_line.text
        bbox = ocr_line.bbox
        line_width = bbox.x2 - bbox.x1

        # 在行文本中查找目标文本的位置（先尝试原始文本）
        idx = line_text.find(text)
        search_text = text
        
        if idx < 0:
            # 去掉标点后查找
            line_clean = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', line_text)
            text_clean = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', text)
            idx = line_clean.find(text_clean)
            if idx < 0:
                # 再尝试逐字匹配：找到包含最多目标字符的位置
                return self._approximate_char_bbox(text, ocr_line)
            search_text = text_clean
            line_text = line_clean

        # 计算字符位置比例（更精确：按字符数而非字节数）
        total_chars = len(line_text) or 1
        text_chars = len(search_text)
        start_ratio = idx / total_chars
        end_ratio = (idx + text_chars) / total_chars

        x1 = bbox.x1 + int(line_width * start_ratio)
        x2 = bbox.x1 + int(line_width * end_ratio)

        # 确保最小宽度（至少覆盖一个字符）
        if x2 - x1 < 20:
            x2 = x1 + 20

        return BoundingBox(x1, bbox.y1, x2, bbox.y2)

    def _approximate_char_bbox(self, text: str, ocr_line) -> BoundingBox:
        """
        当精确匹配失败时，使用逐字近似定位。
        找到包含最多目标字符的子区域。
        """
        line_text = ocr_line.text
        bbox = ocr_line.bbox
        line_width = bbox.x2 - bbox.x1
        
        clean_line = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', line_text)
        clean_text = re.sub(r'[，。、；：！？\s,.\!\?\;\:\-]', '', text)
        
        # 滑动窗口：找到包含最多目标字符的连续区域
        best_start = 0
        best_end = 0
        best_count = 0
        
        for i in range(len(clean_line)):
            for j in range(i + 1, min(i + len(clean_text) + 3, len(clean_line) + 1)):
                window = clean_line[i:j]
                count = sum(1 for c in clean_text if c in window)
                if count > best_count:
                    best_count = count
                    best_start = i
                    best_end = j
        
        total_chars = len(clean_line) or 1
        start_ratio = best_start / total_chars
        end_ratio = best_end / total_chars
        
        x1 = bbox.x1 + int(line_width * start_ratio)
        x2 = bbox.x1 + int(line_width * end_ratio)
        
        # 确保最小宽度
        if x2 - x1 < 20:
            x2 = x1 + 20
        
        return BoundingBox(x1, bbox.y1, x2, bbox.y2)
