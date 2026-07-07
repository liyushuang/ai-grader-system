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
from pathlib import Path
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
        max_tokens: int = 8192,
        llm_timeout_seconds: int = None,
    ):
        self.dashscope_api_key = dashscope_api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.baidu_api_key = baidu_api_key or os.environ.get("BAIDU_API_KEY", "")
        self.baidu_secret_key = baidu_secret_key or os.environ.get("BAIDU_SECRET_KEY", "")
        self.volcano_api_key = volcano_api_key or os.environ.get("VOLCANO_API_KEY", "")
        self.llm_provider = llm_provider.lower()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.llm_timeout_seconds = int(
            llm_timeout_seconds or os.environ.get("FUSION_LLM_TIMEOUT_SECONDS", "90")
        )
        if self.llm_provider == "volcano":
            self.model = model or os.environ.get("VOLCANO_MODEL", "doubao-seed-2-1-pro-260628")
        else:
            self.model = model or os.environ.get("FUSION_QWEN_MODEL", "qwen-plus")

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

            # ── Phase 2: 清洗、动态对齐、规则引擎预处理 ──
            print("[Fusion] Phase 2: OCR清洗 + 动态对齐 + 规则初判...")
            sentence_analyses, clean_lines, segments, aligned, debug_data = self._run_rule_pipeline(
                grading_input, ocr_lines, full_text
            )

            # ── Phase 3: 构建预处理摘要 ──
            print("[Fusion] Phase 3: 构建LLM提示...")
            pre_judgment = self._build_pre_judgment(sentence_analyses, aligned)

            # ── Phase 4: LLM终判 ──
            print(f"[Fusion] Phase 4: {self.llm_provider.upper()} 终判...")
            try:
                llm_result = self._run_llm_final(
                    grading_input, full_text, pre_judgment
                )
            except Exception as exc:
                print(f"[Fusion] LLM终判失败，返回规则结果: {exc}")
                result = self._build_rule_only_result(
                    grading_input, full_text, sentence_analyses, start_time, str(exc)
                )
                self._write_pipeline_debug(grading_input, debug_data, result)
                return result

            # ── Phase 5: 融合坐标 ──
            print("[Fusion] Phase 5: 融合坐标...")
            result = self._fuse_results(
                sentence_analyses, ocr_lines, llm_result,
                grading_input, start_time,
            )
            self._preserve_high_confidence_rules(result, sentence_analyses)
            self._write_pipeline_debug(grading_input, debug_data, result)

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

            # ── Phase 2: OCR 文本清洗 ──
            from assignment_pipeline import (
                AssignmentSegmenter, OCRCleaner, AlignmentEngine, pipeline_debug_dict
            )
            from rule_engine import RuleEngine

            yield {"type": "stage", "stage": "clean", "message": "🧹 正在过滤页眉、品牌、涂改符和无效文字..."}
            cleaner = OCRCleaner()
            clean_lines = cleaner.clean_lines(ocr_lines)
            body_lines = [line for line in clean_lines if not line.skipped]
            yield {"type": "stage", "stage": "clean_done",
                   "message": f"✅ 文本清洗完成：保留 {len(body_lines)} 行正文，过滤 {len(clean_lines) - len(body_lines)} 行噪声"}

            # ── Phase 3: 任务标准对齐 ──
            yield {"type": "stage", "stage": "align", "message": "🧭 正在根据当前作业标准生成批改单元并对齐 OCR 行..."}
            segmenter = AssignmentSegmenter(
                textbook_name=grading_input.textbook_name,
                grading_rules=grading_input.grading_rules,
            )
            segments = segmenter.build_segments()
            aligned = AlignmentEngine().align(body_lines, segments)
            aligned_count = sum(1 for item in aligned if item.student_text)
            needs_review_count = sum(1 for item in aligned if item.needs_review)
            yield {"type": "stage", "stage": "align_done",
                   "message": f"✅ 标准对齐完成：{aligned_count}/{len(aligned)} 个单元有作答，{needs_review_count} 个需复核"}

            # ── Phase 4: 规则引擎初判 ──
            yield {"type": "stage", "stage": "rule", "message": "📐 正在识别补主语、重点词、错别字和明显漏译..."}
            engine = RuleEngine()
            sentence_analyses = engine.grade_aligned_segments(aligned)
            self._map_aligned_coords(sentence_analyses, aligned, body_lines)
            locatable_rule_count = sum(1 for sa in sentence_analyses for err in sa.errors if err.bbox)
            debug_data = pipeline_debug_dict(ocr_lines, clean_lines, segments, aligned)
            debug_data["rule"] = {
                "high_confidence_errors": self._rule_error_debug(sentence_analyses),
                "sentence_count": len(sentence_analyses),
                "error_count": sum(len(sa.errors) for sa in sentence_analyses),
                "locatable_error_count": locatable_rule_count,
            }
            debug_data["full_text"] = full_text
            yield {"type": "stage", "stage": "rule_done",
                   "message": f"✅ 规则初判：{len(aligned)} 个批改单元，"
                             f"{sum(len(sa.errors) for sa in sentence_analyses)} 处高置信/候选问题，"
                             f"{locatable_rule_count} 处可定位"}

            # ── Phase 5: 构建预处理摘要 ──
            pre_judgment = self._build_pre_judgment(sentence_analyses, aligned)

            # ── Phase 6: LLM终判（流式）──
            yield {"type": "stage", "stage": "llm", "message": "🧠 AI 正在分析..."}
            system_prompt = self._build_llm_system_prompt(
                grading_input, full_text, pre_judgment
            )

            try:
                # 流式调用 LLM
                llm_buffer = ""
                for chunk in self._run_llm_stream(grading_input, system_prompt, full_text, pre_judgment):
                    if chunk:
                        llm_buffer += chunk
                        yield {"type": "llm_chunk", "text": chunk}

                # 解析 LLM 结果
                if self.llm_provider == "volcano":
                    from volcano_grader import VolcanoGrader
                    llm = VolcanoGrader(api_key=self.volcano_api_key)
                    llm_result = llm._parse_response(llm_buffer, grading_input)
                    llm_result = llm._post_process(llm_result)
                else:
                    llm_result = self._parse_review_response(llm_buffer, grading_input)
                if hasattr(llm_result, "review_payload"):
                    review_count = len(llm_result.review_payload.get("confirmed_rule_errors", []))
                    add_count = len(llm_result.review_payload.get("add_errors", []))
                    message = f"✅ AI复核完成：复核 {review_count} 个规则候选，补充 {add_count} 个候选"
                else:
                    message = f"✅ AI 分析完成：{llm_result.total_score}分，{llm_result.total_errors} 处错误"
                yield {"type": "stage", "stage": "llm_done", "message": message}
            except Exception as exc:
                result = self._build_rule_only_result(
                    grading_input, full_text, sentence_analyses, start_time, str(exc)
                )
                self._write_pipeline_debug(grading_input, debug_data, result)
                from utils.annotation_utils import generate_annotations_from_result, annotations_to_dict_list
                annotations = generate_annotations_from_result(result)
                yield {"type": "stage", "stage": "llm_timeout",
                       "message": "⚠️ AI复核超时，已先返回规则初判结果"}
                yield {"type": "result", "data": self._stream_result_data(result, annotations)}
                return

            # ── Phase 7: 融合坐标 ──
            yield {"type": "stage", "stage": "fuse", "message": "🔗 正在融合模型复核结果与 OCR 坐标..."}
            result = self._fuse_results(
                sentence_analyses, ocr_lines, llm_result,
                grading_input, start_time,
            )
            self._preserve_high_confidence_rules(result, sentence_analyses)
            self._write_pipeline_debug(grading_input, debug_data, result)
            yield {"type": "stage", "stage": "fuse_done",
                   "message": f"✅ 标注就绪：{sum(len(sa.errors) for sa in result.sentence_analyses)} 处错误，"
                             f"{sum(1 for sa in result.sentence_analyses if sa.is_excellent)} 个精彩句，"
                             f"{sum(1 for sa in result.sentence_analyses if sa.is_highlight)} 个点睛句"}

            # 生成标注
            from utils.annotation_utils import generate_annotations_from_result, annotations_to_dict_list
            annotations = generate_annotations_from_result(result)

            # 返回最终结果
            yield {"type": "result", "data": self._stream_result_data(result, annotations)}

        except Exception as e:
            yield {"type": "error", "message": f"批改异常: {str(e)}"}

    def _stream_result_data(self, result: GradingResult, annotations: list) -> dict:
        from utils.annotation_utils import annotations_to_dict_list
        return {
                "total_score": result.total_score,
                "total_errors": result.total_errors,
                "overall_comment": result.overall_comment,
                "overall_comment_general": result.overall_comment_general,
                "overall_comment_encouraging": result.overall_comment_encouraging,
                "overall_comment_instructive": result.overall_comment_instructive,
                "polished_full_translation": result.polished_full_translation,
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
                "pipeline_debug_path": getattr(result, "pipeline_debug_path", ""),
                "annotations": annotations_to_dict_list(annotations),
                "sentence_analyses": [
                    {
                        "original_classical": sa.original_classical,
                        "student_translation": sa.student_translation,
                        "standard_translation": sa.standard_translation,
                        "polished_translation": sa.polished_translation,
                        "sentence_score": sa.sentence_score,
                        "is_excellent": sa.is_excellent,
                        "is_highlight": sa.is_highlight,
                        "highlight_comment": sa.highlight_comment,
                        "errors": [
                            {
                                "error_type": e.error_type.value,
                                "original_text": e.original_text,
                                "correct_text": e.correct_text,
                                "reason": e.reason,
                                "deduction_points": e.deduction_points,
                                "bbox": e.bbox.to_list() if e.bbox else None,
                            }
                            for e in sa.errors
                        ],
                    }
                    for sa in result.sentence_analyses
                ],
            }

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

    def _run_rule_pipeline(self, inp: GradingInput, ocr_lines: list, full_text: str):
        """OCR 行清洗 → 任务标准分段 → 动态对齐 → 规则初判 → 坐标回填。"""
        from assignment_pipeline import (
            AssignmentSegmenter, OCRCleaner, AlignmentEngine, pipeline_debug_dict
        )
        from rule_engine import RuleEngine

        cleaner = OCRCleaner()
        clean_line_views = cleaner.clean_lines(ocr_lines)
        body_lines = [line for line in clean_line_views if not line.skipped]

        segmenter = AssignmentSegmenter(
            textbook_name=inp.textbook_name,
            grading_rules=inp.grading_rules,
        )
        segments = segmenter.build_segments()
        aligned = AlignmentEngine().align(body_lines, segments)

        engine = RuleEngine()
        sentence_analyses = engine.grade_aligned_segments(aligned)
        self._map_aligned_coords(sentence_analyses, aligned, body_lines)

        debug_data = pipeline_debug_dict(ocr_lines, clean_line_views, segments, aligned)
        debug_data["rule"] = {
            "high_confidence_errors": self._rule_error_debug(sentence_analyses),
            "sentence_count": len(sentence_analyses),
            "error_count": sum(len(sa.errors) for sa in sentence_analyses),
        }
        debug_data["full_text"] = full_text
        return sentence_analyses, clean_line_views, segments, aligned, debug_data

    def _map_aligned_coords(self, analyses: List[SentenceAnalysis], aligned: list, body_lines: list):
        for idx, sa in enumerate(analyses):
            aligned_item = aligned[idx] if idx < len(aligned) else None
            if aligned_item and aligned_item.bbox:
                sa.bbox = aligned_item.bbox

            for err in sa.errors:
                err.bbox = self._locate_error_bbox(err, aligned_item, body_lines)

    def _locate_error_bbox(self, err: ErrorItem, aligned_item, body_lines: list) -> Optional[BoundingBox]:
        if not aligned_item or not err.original_text:
            return None
        search_text = self._clean_for_match(err.original_text)
        if not search_text:
            return None

        err_text = f"{err.original_text}{err.correct_text}{err.reason}"
        if "主语" in err_text and aligned_item.lines:
            bbox = self._locate_subject_bbox(err, aligned_item, body_lines)
            if bbox:
                return bbox

        for line in aligned_item.lines:
            if search_text not in self._clean_for_match(line.text):
                continue
            anchor_ids, bbox = line.anchor_span_for_text(search_text) if hasattr(line, "anchor_span_for_text") else ([], None)
            if bbox:
                err.anchor_ids = anchor_ids
                return bbox

        return None

    def _locate_subject_bbox(self, err: ErrorItem, aligned_item, body_lines: list) -> Optional[BoundingBox]:
        """主语类问题优先绑定到 OCR 已识别出的真实主语字，而不是粗暴取句首。"""
        search_terms = self._subject_search_terms(err)
        if not search_terms:
            return None

        candidate_lines = []
        first_line_no = min((line.line_no for line in aligned_item.lines), default=None)
        if first_line_no is not None:
            previous = [
                line for line in body_lines
                if getattr(line, "line_no", 0) < first_line_no and not getattr(line, "skipped", False)
            ]
            if previous:
                candidate_lines.append((previous[-1], True))

        candidate_lines.extend((line, False) for line in aligned_item.lines)

        for line, prefer_last in candidate_lines:
            for term in search_terms:
                if self._clean_for_match(term) not in self._clean_for_match(line.text):
                    continue
                anchor_ids, bbox = line.anchor_span_for_text(term, prefer_last=prefer_last) if hasattr(line, "anchor_span_for_text") else ([], None)
                if bbox:
                    err.anchor_ids = anchor_ids
                    return bbox

        line = aligned_item.lines[0]
        anchors = getattr(line, "char_anchors", [])[:1]
        if anchors:
            err.anchor_ids = [anchor.anchor_id for anchor in anchors]
            return self._bbox_from_anchor_objects(anchors)
        if line.bbox:
            width = max(36, min(80, line.bbox.width // 8))
            return BoundingBox(line.bbox.x1, line.bbox.y1, line.bbox.x1 + width, line.bbox.y2)
        return None

    def _subject_search_terms(self, err: ErrorItem) -> list:
        raw_terms = []
        for value in (err.original_text, err.correct_text, err.reason):
            if not value:
                continue
            raw_terms.extend(re.split(r"[/、，,；;：:\s]+", str(value)))
        terms = []
        for term in raw_terms:
            cleaned = self._clean_for_match(term)
            if cleaned and cleaned not in terms and any(ch in cleaned for ch in "我余吾"):
                terms.append(cleaned)
        return sorted(terms, key=len, reverse=True)

    def _bbox_from_anchor_objects(self, anchors: list) -> Optional[BoundingBox]:
        anchors = [anchor for anchor in anchors if getattr(anchor, "bbox", None)]
        if not anchors:
            return None
        return BoundingBox(
            min(anchor.bbox.x1 for anchor in anchors),
            min(anchor.bbox.y1 for anchor in anchors),
            max(anchor.bbox.x2 for anchor in anchors),
            max(anchor.bbox.y2 for anchor in anchors),
        )

    def _clean_for_match(self, text: str) -> str:
        return re.sub(r'[，。、；：！？\s,.\!\?\;\:\-☰]', '', text or '')

    def _rule_error_debug(self, analyses: List[SentenceAnalysis]) -> list:
        rows = []
        for si, sa in enumerate(analyses):
            for ei, err in enumerate(sa.errors):
                rows.append({
                    "sentence_index": si,
                    "error_index": ei,
                    "type": getattr(err.error_type, "value", err.error_type),
                    "original_text": err.original_text,
                    "correct_text": err.correct_text,
                    "reason": err.reason,
                    "deduction_points": err.deduction_points,
                    "locatable": bool(err.bbox),
                    "bbox": err.bbox.to_list() if err.bbox else None,
                    "anchor_ids": getattr(err, "anchor_ids", []),
                    "high_confidence": self._is_high_confidence_rule(err),
                })
        return rows

    def _write_pipeline_debug(self, inp: GradingInput, debug_data: dict, result: GradingResult):
        try:
            debug_dir = Path("output") / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            image_name = Path(inp.image_path).stem if inp.image_path else f"image_{int(time.time())}"
            path = debug_dir / f"{image_name}_pipeline_debug.json"
            debug_data["final"] = {
                "total_score": result.total_score,
                "total_errors": result.total_errors,
                "dimension_scores": result.dimension_scores,
                "review_payload": getattr(result, "review_payload", None),
                "annotations": [
                    {
                        "sentence_index": idx,
                        "student_translation": sa.student_translation,
                        "errors": [
                            {
                                "type": getattr(e.error_type, "value", e.error_type),
                                "original_text": e.original_text,
                                "correct_text": e.correct_text,
                                "reason": e.reason,
                                "bbox": e.bbox.to_list() if e.bbox else None,
                                "anchor_ids": getattr(e, "anchor_ids", []),
                            }
                            for e in sa.errors
                        ],
                    }
                    for idx, sa in enumerate(result.sentence_analyses)
                ],
            }
            path.write_text(json.dumps(debug_data, ensure_ascii=False, indent=2), encoding="utf-8")
            result.pipeline_debug_path = str(path)
        except Exception as exc:
            print(f"[Fusion] debug输出失败: {exc}")

    def _build_rule_only_result(
        self,
        inp: GradingInput,
        full_text: str,
        sentence_analyses: List[SentenceAnalysis],
        start_time: float,
        error_message: str = "",
    ) -> GradingResult:
        deductions = 0.0
        for sa in sentence_analyses:
            for err in sa.errors:
                if self._is_high_confidence_rule(err):
                    deductions += err.deduction_points
                elif err.bbox:
                    deductions += err.deduction_points * 0.5
                else:
                    deductions += err.deduction_points * 0.25
        score = max(0, min(100, 100 - deductions * 2))
        located = sum(1 for sa in sentence_analyses for e in sa.errors if e.bbox)
        total_errors = sum(len(sa.errors) for sa in sentence_analyses)
        completed = sum(
            1 for sa in sentence_analyses
            if sa.student_translation and not sa.student_translation.startswith("（未识别")
        )
        result = GradingResult(
            recognized_text=full_text,
            sentence_analyses=sentence_analyses,
            total_score=score,
            overall_comment=(
                f"已完成OCR、文本清洗、任务标准对齐和规则初判；因模型复核超时或失败，"
                f"当前展示规则批改结果。共识别到{completed}个批改单元，发现{total_errors}处候选问题，"
                f"其中{located}处可定位到画布。"
            ),
            confidence=Confidence.MEDIUM,
            status=GradingStatus.LOW_CONFIDENCE,
            error_message=error_message,
            grader_name=self.name,
            processing_time_ms=int((time.time() - start_time) * 1000),
            homework_completion=f"当前图片可对齐到{completed}个批改单元，未覆盖部分不按漏译直接扣分。",
            strengths=["已按当前图片内容完成逐句对齐", "高置信规则已保留"],
            weaknesses=["模型复核未完成，低置信问题建议人工再看一遍"],
            suggestions=["优先检查画布中可定位的错字、重点词和补主语问题"],
            system_tags=["规则初判", "模型复核未完成"],
            dimension_scores={
                "完整度": min(20, int(completed / max(len(sentence_analyses), 1) * 20)),
                "准确度": max(0, 20 - min(20, deductions)),
                "重点词掌握": max(0, 20 - min(20, deductions)),
                "句式处理": 15,
                "表达流畅度": 15,
                "忠实原文": max(0, 20 - min(20, deductions // 2)),
            },
        )
        return result

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

    def _build_pre_judgment(self, analyses: List[SentenceAnalysis], aligned_segments: list = None) -> str:
        """构建预处理摘要，供LLM参考"""
        lines = [
            "## 规则引擎预处理结果",
            "说明：anchor_id 是 OCR 识别出的字级锚点。你只能引用这些 anchor_id，不能创建或修改锚点。",
            "high_confidence=true 的错误是本地规则命中的老师式高置信问题，必须保留；低置信内容仅供复核。",
        ]
        for i, sa in enumerate(analyses, 1):
            status = []
            if sa.errors:
                status.append(f"发现 {len(sa.errors)} 个错误")
            if sa.is_excellent:
                status.append("翻译优秀")
            if not status:
                status.append("无明显错误")
            lines.append(f"segment_id={i}. {sa.original_classical} → {sa.student_translation} ({', '.join(status)})")
            if aligned_segments and i - 1 < len(aligned_segments):
                anchor_line = self._format_segment_anchor_context(aligned_segments[i - 1])
                if anchor_line:
                    lines.append(f"   OCR anchors: {anchor_line}")
            for err_idx, err in enumerate(sa.errors):
                level = "high_confidence" if self._is_high_confidence_rule(err) else "review_candidate"
                loc = "locatable" if err.bbox else "not_locatable"
                anchor_ids = ",".join(getattr(err, "anchor_ids", []) or [])
                lines.append(
                    f"   - error_index={err_idx} [{level}/{loc}] {getattr(err.error_type, 'value', err.error_type)}："
                    f"{err.original_text} → {err.correct_text}；anchor_ids=[{anchor_ids}]；{err.reason}"
                )
        return "\n".join(lines)

    def _format_segment_anchor_context(self, aligned_item) -> str:
        chunks = []
        for line in getattr(aligned_item, "lines", []) or []:
            anchors = getattr(line, "char_anchors", []) or []
            if not anchors:
                continue
            # Keep context compact but deterministic: every OCR char has its anchor id.
            parts = [f"{anchor.anchor_id}:{anchor.text}" for anchor in anchors]
            chunks.append(f"line{line.line_no} " + " ".join(parts))
        return " | ".join(chunks)

    def _build_fusion_system_prompt(self, inp: GradingInput, ocr_text: str,
                                     pre_judgment: str) -> str:
        """构建 Qwen 文本复核 Prompt：只做批改推理，不处理坐标。"""
        from qwen_vl_max_grader import QwenVLMaxGrader

        sentence_pairs = QwenVLMaxGrader._default_sentence_pairs()

        return f"""你是资深中学语文教师，专门复核《{inp.textbook_name}》文言文翻译作业。

你的职责：只做“文本批改推理”，不要输出坐标、bbox、画线位置。
坐标会由后续程序用 OCR bbox 回填。你只需要判断哪些问题成立、哪些不成立、补充少量高价值问题，并生成报告。

## 逐句精确参照（必须逐句严格对照）
{sentence_pairs}

## OCR学生译文
{ocr_text}

## 规则初判候选
{pre_judgment}

## 复核硬约束
1. high_confidence 候选必须保留；只能优化报告措辞，不能驳回。
2. review_candidate 必须逐条判断 confirm 或 reject。若学生文本中有语义等价表达，应 reject。
3. 你可以补充 add_errors，但仅限“错别字/不规范字”；必须引用 OCR anchors 中存在的 anchor_ids，且 anchor_ids 拼出的文字必须等于 evidence_text；最多补充 1 条。
4. 不要输出 bbox、坐标、画线位置。
5. 语义不准、漏译、重点词理解不到位等问题只写入 report.weaknesses 或 suggestions，不要加入 add_errors。
6. 批改对象是文言文翻译，不是作文赏析；优先看重点词、补主语、错别字、特殊句式。
7. 输出必须是纯 JSON，不要 markdown。
8. OCR 噪声或长句误译，例如“雪白的曝光倾泄而下”这类内容，不要加入 add_errors；最多写进 report.weaknesses。
9. highlights 只允许输出真正像老师旁批的短句，例如“点睛句：石底奇观理解到位”，不要写“情感基调”“全篇感情”这类泛泛赏析。
10. 如果不能确定 anchor_ids 与 evidence_text 完全对应，不要输出 add_errors。

## 输出结构
{{
  "confirmed_rule_errors": [
    {{
      "segment_id": 1,
      "error_index": 0,
      "action": "confirm|reject",
      "reason": "短理由"
    }}
  ],
  "add_errors": [
    {{
      "segment_id": 1,
      "error_type": "实词错误|虚词错误|漏译|多译|错别字|语序错误|标点错误",
      "anchor_ids": ["l12_c10", "l12_c11"],
      "evidence_text": "必须原样出现在OCR中的词或短语",
      "correct_text": "正确写法或译法",
      "reason": "短理由",
      "deduction_points": 2,
      "confidence": "high|medium|low"
    }}
  ],
  "highlights": [
    {{
      "segment_id": 3,
      "type": "highlight|excellent",
      "comment": "12-25字短旁批"
    }}
  ],
  "report": {{
    "total_score": 80,
    "overall_comment": "100字内总评，必须基于当前OCR内容",
    "overall_comment_general": "同overall_comment",
    "overall_comment_encouraging": "鼓励性反馈",
    "overall_comment_instructive": "指导性反馈",
    "polished_full_translation": "基于当前OCR内容的润色译文",
    "homework_completion": "完成情况",
    "strengths": ["具体优点"],
    "weaknesses": ["具体问题"],
    "suggestions": ["可操作建议"],
    "parent_feedback": "50-80字家长反馈",
    "system_tags": ["文言文翻译"],
    "confidence": "高"
  }},
  "dimension_scores": {{"完整度":N,"准确度":N,"重点词掌握":N,"句式处理":N,"表达流畅度":N,"忠实原文":N}},
  "dimension_analysis": {{}}
}}"""

    # ── Phase 4: LLM终判 ─────────────────────────

    def _run_llm_final(self, inp: GradingInput, ocr_text: str,
                       pre_judgment: str) -> GradingResult:
        """调用 LLM 进行终判（支持 Qwen 和 Volcano）"""
        system_prompt = self._build_llm_system_prompt(inp, ocr_text, pre_judgment)
        user_content = self._build_text_only_user_content(inp, ocr_text, pre_judgment)

        if self.llm_provider == "volcano":
            from volcano_grader import VolcanoGrader
            volcano = VolcanoGrader(
                api_key=self.volcano_api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            raw_response, token_usage = volcano._call_api(system_prompt, user_content)
            result = volcano._parse_response(raw_response, inp)
            result = volcano._post_process(result)
            result.token_usage = token_usage
            return result
        else:
            from qwen_vl_max_grader import QwenVLMaxGrader
            qwen = QwenVLMaxGrader(
                api_key=self.dashscope_api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout_seconds=self.llm_timeout_seconds,
            )
            raw_response, token_usage = qwen._call_api(system_prompt, user_content)
            result = self._parse_review_response(raw_response, inp)
            result.token_usage = token_usage
            return result

    def _parse_review_response(self, raw: str, inp: GradingInput) -> GradingResult:
        from qwen_vl_max_grader import QwenVLMaxGrader

        cleaned = QwenVLMaxGrader()._extract_json(raw)
        data = json.loads(cleaned)
        report = data.get("report", {}) if isinstance(data.get("report"), dict) else {}
        result = GradingResult(
            recognized_text="",
            total_score=report.get("total_score", data.get("total_score", 0)),
            overall_comment=report.get("overall_comment", data.get("overall_comment", "")),
            overall_comment_general=report.get("overall_comment_general", report.get("overall_comment", "")),
            overall_comment_encouraging=report.get("overall_comment_encouraging", ""),
            overall_comment_instructive=report.get("overall_comment_instructive", ""),
            polished_full_translation=report.get("polished_full_translation", ""),
            confidence=self._parse_confidence_value(report.get("confidence", data.get("confidence", "中"))),
            raw_response=raw,
        )
        result.dimension_scores = data.get("dimension_scores", result.dimension_scores)
        result.dimension_analysis = data.get("dimension_analysis", {})
        result.homework_completion = report.get("homework_completion", "")
        result.strengths = report.get("strengths", [])
        result.weaknesses = report.get("weaknesses", [])
        result.suggestions = report.get("suggestions", [])
        result.parent_feedback = report.get("parent_feedback", "")
        result.system_tags = report.get("system_tags", [])
        result.review_payload = data
        return result

    def _parse_confidence_value(self, value) -> Confidence:
        mapping = {"high": "高", "medium": "中", "low": "低"}
        text = mapping.get(str(value).lower(), value or "中")
        try:
            return Confidence(text)
        except Exception:
            return Confidence.MEDIUM

    def _build_text_only_user_content(self, inp: GradingInput, ocr_text: str,
                                      pre_judgment: str) -> list:
        return [{
            "type": "text",
            "text": (
                f"请批改《{inp.textbook_name}》文言文翻译作业。\n\n"
                f"【百度OCR识别到的学生译文】\n{ocr_text}\n\n"
                f"【规则引擎初判】\n{pre_judgment}\n\n"
                "只依据以上 OCR 文本和标准答案进行语义批改；不要假设图片里还有额外内容。"
                "请严格按系统提示返回 JSON。"
            )
        }]

    def _run_llm_stream(self, inp: GradingInput, system_prompt: str,
                        ocr_text: str, pre_judgment: str):
        """流式调用 LLM，逐 token 返回纯文本字符串（支持 Qwen 和 Volcano）"""
        user_content = self._build_text_only_user_content(inp, ocr_text, pre_judgment)

        if self.llm_provider == "volcano":
            from volcano_grader import VolcanoGrader
            volcano = VolcanoGrader(
                api_key=self.volcano_api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
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
                timeout_seconds=self.llm_timeout_seconds,
            )
            for event in qwen._call_api_stream(system_prompt, user_content):
                if event.get("type") == "llm_chunk":
                    yield event["text"]
                elif event.get("type") == "llm_error":
                    raise Exception(event.get("message", "LLM API 调用失败"))
            # llm_done、llm_retry 等事件忽略，由外部根据 buffer 判断完成

    def _build_llm_system_prompt(self, inp: GradingInput, ocr_text: str,
                                 pre_judgment: str) -> str:
        if self.llm_provider == "volcano":
            return self._build_volcano_light_system_prompt(inp, ocr_text, pre_judgment)
        return self._build_fusion_system_prompt(inp, ocr_text, pre_judgment)

    def _build_volcano_light_system_prompt(self, inp: GradingInput, ocr_text: str,
                                           pre_judgment: str) -> str:
        from qwen_vl_max_grader import QwenVLMaxGrader
        sentence_pairs = QwenVLMaxGrader._default_sentence_pairs()
        return f"""你是语文老师，批改《{inp.textbook_name}》文言文翻译。不要展开推理，直接输出 JSON。

【标准原文和译文】
{sentence_pairs}

【批改原则】
1. 只依据用户提供的 OCR 学生译文批改。
2. 只标最关键问题，errors 最多2处；优秀句最多2处；点睛句最多2处。
3. 错误必须具体到词或短语，reason 不超过25字。
4. 不要把未翻译的后半篇逐句展开，只在总评中说明“后半部分未完成”。
5. 输出必须是纯 JSON，不能输出解释、思考过程或 markdown。

【只输出这个结构】
{{
  "recognized_text": "OCR学生译文",
  "sentence_analysis": [
    {{
      "original_classical": "对应原文",
      "student_translation": "学生译文片段",
      "standard_translation": "标准译文",
      "polished_translation": "简短润色译文",
      "errors": [
        {{
          "error_type": "实词错误|漏译|错别字|表达不准",
          "original_text": "错误词",
          "correct_text": "正确译法",
          "reason": "短理由",
          "deduction_points": 2
        }}
      ],
      "sentence_score": 85,
      "is_excellent": false,
      "is_highlight": false,
      "highlight_comment": ""
    }}
  ],
  "total_score": 80,
  "overall_comment": "80字内总评",
  "overall_comment_general": "80字内总评",
  "overall_comment_encouraging": "60字内鼓励",
  "overall_comment_instructive": "60字内建议",
  "polished_full_translation": "简短润色译文",
  "dimension_scores": {{"完整度":15,"准确度":15,"重点词掌握":15,"句式处理":15,"表达流畅度":15,"忠实原文":15}},
  "dimension_analysis": {{}},
  "homework_completion": "完成情况",
  "strengths": ["优点1"],
  "weaknesses": ["问题1"],
  "suggestions": ["建议1"],
  "highlight_sentences": [],
  "parent_feedback": "50字内家长反馈",
  "system_tags": ["文言文翻译"],
  "confidence": "高"
}}"""

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
        if hasattr(llm_result, "review_payload"):
            return self._fuse_review_results(rule_analyses, ocr_lines, llm_result, start_time)

        # 兼容旧格式：规则结果作为主结果；模型只补充报告和少量可验证问题，避免幻觉标注直接进入画布。
        fused_analyses = self._clone_rule_analyses(rule_analyses)

        # 构建规则引擎的坐标索引：{student_translation_hash: (sentence_bbox, {error_text: bbox})}
        rule_index = {}
        for rsa in fused_analyses:
            if rsa.student_translation and not rsa.student_translation.startswith("（未"):
                err_map = {}
                for e in rsa.errors:
                    if e.original_text and e.bbox:
                        err_map[e.original_text] = e.bbox
                rule_index[rsa.student_translation] = (rsa.bbox, err_map)

        total_mapped = 0
        total_errors_mapped = 0

        accepted_model_errors = 0
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

            target = self._find_matching_sentence_in_list(fused_analyses, sa)
            if target:
                if sa.is_highlight and sa.bbox and not target.is_highlight and self._is_key_highlight(sa):
                    target.is_highlight = True
                    target.highlight_comment = sa.highlight_comment
                if sa.is_excellent and sa.bbox and not target.errors:
                    target.is_excellent = True
                    target.polished_translation = sa.polished_translation
                for error in sa.errors:
                    if self._should_accept_model_error(error, target, full_text=self._join_ocr_text(ocr_lines)):
                        if not self._has_similar_error(target.errors, error):
                            target.errors.append(error)
                            accepted_model_errors += 1

        print(f"[Fusion] 坐标映射: {total_mapped} 句, {total_errors_mapped} 个错误")
        print(f"[Fusion] 模型补充问题采纳: {accepted_model_errors} 个")

        llm_result.sentence_analyses = fused_analyses
        llm_result.total_score = self._score_from_analyses(fused_analyses, llm_result.total_score)
        llm_result.grader_name = self.name
        llm_result.processing_time_ms = int((time.time() - start_time) * 1000)
        llm_result.normalize_scores()
        return llm_result

    def _fuse_review_results(
        self,
        rule_analyses: List[SentenceAnalysis],
        ocr_lines: list,
        review_result: GradingResult,
        start_time: float,
    ) -> GradingResult:
        payload = getattr(review_result, "review_payload", {}) or {}
        fused_analyses = self._clone_rule_analyses(rule_analyses)
        for sa in fused_analyses:
            sa.is_highlight = False
            sa.is_excellent = False
            sa.highlight_comment = ""
        decisions = self._review_decision_map(payload)

        for si, sa in enumerate(fused_analyses, 1):
            kept = []
            for ei, err in enumerate(sa.errors):
                if self._is_high_confidence_rule(err):
                    kept.append(err)
                    continue
                action = decisions.get((si, ei))
                if action == "confirm":
                    kept.append(err)
            sa.errors = kept

        anchor_index = self._build_ocr_anchor_index(ocr_lines)
        for item in payload.get("add_errors", [])[:2]:
            try:
                segment_id = int(item.get("segment_id", 0))
            except Exception:
                continue
            if not 1 <= segment_id <= len(fused_analyses):
                continue
            anchor_ids = item.get("anchor_ids") or []
            evidence = item.get("evidence_text") or item.get("original_text") or ""
            anchor_text, anchor_bbox = self._resolve_anchor_span(anchor_ids, anchor_index)
            if not evidence or not anchor_ids or not anchor_bbox:
                continue
            if self._clean_for_match(anchor_text) != self._clean_for_match(evidence):
                continue
            if not self._can_accept_review_add_error(item):
                continue
            target = fused_analyses[segment_id - 1]
            err = ErrorItem(
                error_type=self._parse_error_type_value(item.get("error_type", "")),
                original_text=evidence,
                correct_text=item.get("correct_text", ""),
                reason=item.get("reason", ""),
                deduction_points=int(item.get("deduction_points", 2) or 2),
                bbox=anchor_bbox,
            )
            err.anchor_ids = anchor_ids
            err.model_added = True
            if err.bbox and not self._has_similar_error(target.errors, err):
                target.errors.append(err)

        for item in payload.get("highlights", [])[:2]:
            try:
                segment_id = int(item.get("segment_id", 0))
            except Exception:
                continue
            if not 1 <= segment_id <= len(fused_analyses):
                continue
            if not self._can_accept_review_highlight(item):
                continue
            target = fused_analyses[segment_id - 1]
            if item.get("type") == "excellent" and not target.errors:
                target.is_excellent = True
            else:
                target.is_highlight = True
            target.highlight_comment = item.get("comment", "") or target.highlight_comment

        review_result.sentence_analyses = fused_analyses
        review_result.total_score = self._score_from_analyses(fused_analyses, review_result.total_score)
        review_result.dimension_scores = self._calibrate_dimension_scores(
            review_result.total_score,
            review_result.dimension_scores,
        )
        review_result.grader_name = self.name
        review_result.processing_time_ms = int((time.time() - start_time) * 1000)
        review_result.normalize_scores()
        print(f"[Fusion] review融合: {sum(len(sa.errors) for sa in fused_analyses)} 个问题")
        return review_result

    def _calibrate_dimension_scores(self, total_score: int, scores: dict) -> dict:
        keys = ["完整度", "准确度", "重点词掌握", "句式处理", "表达流畅度", "忠实原文"]
        expected = max(0, min(20, round((total_score or 0) / 5)))
        numeric = [
            int(v) for k, v in (scores or {}).items()
            if k in keys and isinstance(v, (int, float))
        ]
        if numeric:
            avg = sum(numeric) / len(numeric)
            if expected - 4 <= avg <= expected + 4:
                return {k: max(0, min(20, int((scores or {}).get(k, expected)))) for k in keys}

        return {
            "完整度": min(20, expected + 1),
            "准确度": expected,
            "重点词掌握": max(0, expected - 1),
            "句式处理": expected,
            "表达流畅度": min(20, expected + 1),
            "忠实原文": max(0, expected - 1),
        }

    def _can_accept_review_add_error(self, item: dict) -> bool:
        """模型补充问题只接受短词级高置信错字/重点词，长句误译默认进报告不画布。"""
        evidence = self._clean_for_match(item.get("evidence_text") or item.get("original_text") or "")
        err_type = item.get("error_type", "")
        confidence = str(item.get("confidence", "")).lower()
        if confidence not in ("high", "高"):
            return False
        if len(evidence) > 6:
            return False
        if any(bad in evidence for bad in ["突然", "曝光", "雪白"]):
            return False
        return ("错别字" in err_type or "不规范" in err_type)

    def _build_ocr_anchor_index(self, ocr_lines: list) -> dict:
        from assignment_pipeline import OCRCleaner
        index = {}
        for line in OCRCleaner().clean_lines(ocr_lines):
            for anchor in getattr(line, "char_anchors", []) or []:
                index[anchor.anchor_id] = anchor
        return index

    def _resolve_anchor_span(self, anchor_ids: list, anchor_index: dict) -> tuple:
        anchors = []
        for anchor_id in anchor_ids:
            anchor = anchor_index.get(anchor_id)
            if not anchor:
                return "", None
            anchors.append(anchor)
        text = "".join(anchor.text for anchor in anchors)
        return text, self._bbox_from_anchor_objects(anchors)

    def _can_accept_review_highlight(self, item: dict) -> bool:
        comment = item.get("comment", "") or ""
        if len(comment) > 28:
            return False
        if any(bad in comment for bad in ["情感基调", "全篇", "生动", "语言"]):
            return False
        return any(ok in comment for ok in ["重点句", "石底", "水清", "翻译准确", "理解到位", "点睛"])

    def _review_decision_map(self, payload: dict) -> dict:
        decisions = {}
        for item in payload.get("confirmed_rule_errors", []):
            try:
                segment_id = int(item.get("segment_id"))
                error_index = int(item.get("error_index"))
            except Exception:
                continue
            action = (item.get("action") or "").lower()
            if action in ("confirm", "reject"):
                decisions[(segment_id, error_index)] = action
        return decisions

    def _parse_error_type_value(self, value: str) -> ErrorType:
        for item in ErrorType:
            if value == item.value or value == item.name:
                return item
        if "错" in value and "字" in value:
            return ErrorType.TYPO
        if "漏" in value:
            return ErrorType.OMISSION
        if "虚" in value:
            return ErrorType.FUNCTION_ERROR
        return ErrorType.CONTENT_ERROR

    def _clone_rule_analyses(self, analyses: List[SentenceAnalysis]) -> List[SentenceAnalysis]:
        cloned = []
        for sa in analyses:
            cloned_errors = []
            for e in sa.errors:
                copied_error = ErrorItem(
                    error_type=e.error_type,
                    original_text=e.original_text,
                    correct_text=e.correct_text,
                    reason=e.reason,
                    deduction_points=e.deduction_points,
                    bbox=e.bbox,
                )
                copied_error.anchor_ids = list(getattr(e, "anchor_ids", []) or [])
                cloned_errors.append(copied_error)
            cloned.append(SentenceAnalysis(
                original_classical=sa.original_classical,
                student_translation=sa.student_translation,
                standard_translation=sa.standard_translation,
                errors=cloned_errors,
                sentence_score=sa.sentence_score,
                is_excellent=sa.is_excellent,
                is_highlight=sa.is_highlight,
                highlight_comment=sa.highlight_comment,
                polished_translation=sa.polished_translation,
                bbox=sa.bbox,
            ))
        return cloned

    def _find_matching_sentence_in_list(self, analyses: List[SentenceAnalysis], source_sa: SentenceAnalysis) -> Optional[SentenceAnalysis]:
        temp = GradingResult(recognized_text="", sentence_analyses=analyses)
        return self._find_matching_sentence(temp, source_sa)

    def _join_ocr_text(self, ocr_lines: list) -> str:
        return "".join(getattr(line, "text", "") or "" for line in ocr_lines)

    def _should_accept_model_error(self, err: ErrorItem, target: SentenceAnalysis, full_text: str) -> bool:
        if not err.bbox:
            return False
        if not err.original_text:
            return False
        if not self._clean_for_match(err.original_text) in self._clean_for_match(full_text):
            return False
        if not self._clean_for_match(err.original_text) in self._clean_for_match(target.student_translation):
            return False
        if self._is_known_false_positive(err, target):
            return False
        if self._is_high_confidence_rule(err):
            return True
        text = f"{getattr(err.error_type, 'value', err.error_type)} {err.original_text} {err.correct_text} {err.reason}"
        return any(k in text for k in ["错字", "不规范", "主语", "重点词"])

    def _is_known_false_positive(self, err: ErrorItem, target: SentenceAnalysis) -> bool:
        text = f"{err.original_text}{err.correct_text}{err.reason}{target.original_classical}"
        if "突然" in text and "呆呆地" in text:
            return True
        if err.original_text in ("佩环", "玉佩玉环") and any("佩环" in e.reason or "珮环" in e.reason for e in target.errors):
            return True
        return False

    def _has_similar_error(self, errors: List[ErrorItem], candidate: ErrorItem) -> bool:
        cand = (self._clean_for_match(candidate.original_text), self._clean_for_match(candidate.correct_text))
        cand_text = f"{candidate.original_text}{candidate.correct_text}{candidate.reason}"
        for err in errors:
            key = (self._clean_for_match(err.original_text), self._clean_for_match(err.correct_text))
            text = f"{err.original_text}{err.correct_text}{err.reason}"
            if cand == key:
                return True
            if ("佩环" in cand_text or "珮环" in cand_text) and ("佩环" in text or "珮环" in text):
                return True
            if candidate.error_type == err.error_type and cand[0] and cand[0] in self._clean_for_match(text):
                return True
        return False

    def _is_key_highlight(self, sa: SentenceAnalysis) -> bool:
        text = f"{sa.original_classical}{sa.highlight_comment}"
        return any(k in text for k in ["全石以为底", "青树翠蔓", "空游无所依", "凄神寒骨", "心乐之"])

    def _score_from_analyses(self, analyses: List[SentenceAnalysis], fallback: int) -> int:
        deductions = 0.0
        for sa in analyses:
            for err in sa.errors:
                if self._is_high_confidence_rule(err):
                    deductions += err.deduction_points
                elif err.bbox:
                    deductions += err.deduction_points * 0.5
                else:
                    deductions += err.deduction_points * 0.25
        rule_score = max(0, min(100, 100 - deductions * 2))
        if fallback:
            return max(0, min(100, int(rule_score * 0.7 + fallback * 0.3)))
        return rule_score

    def _preserve_high_confidence_rules(self, result: GradingResult, rule_analyses: List[SentenceAnalysis]):
        """模型复核后保留本地高置信老师式规则，避免关键旁批被删。"""
        for rule_sa in rule_analyses:
            rule_errors = [e for e in rule_sa.errors if self._is_high_confidence_rule(e)]
            if not rule_errors:
                continue

            target = self._find_matching_sentence(result, rule_sa)
            if not target:
                copied = SentenceAnalysis(
                    original_classical=rule_sa.original_classical,
                    student_translation=rule_sa.student_translation,
                    standard_translation=rule_sa.standard_translation,
                    errors=[],
                    sentence_score=rule_sa.sentence_score,
                    is_excellent=False,
                    is_highlight=rule_sa.is_highlight,
                    highlight_comment=rule_sa.highlight_comment,
                    bbox=rule_sa.bbox,
                )
                result.sentence_analyses.append(copied)
                target = copied

            if not target.bbox and rule_sa.bbox:
                target.bbox = rule_sa.bbox

            existing = {
                (self._clean_for_match(e.original_text), self._clean_for_match(e.correct_text), e.reason)
                for e in target.errors
            }
            for err in rule_errors:
                key = (self._clean_for_match(err.original_text), self._clean_for_match(err.correct_text), err.reason)
                if key in existing:
                    continue
                copied_error = ErrorItem(
                    error_type=err.error_type,
                    original_text=err.original_text,
                    correct_text=err.correct_text,
                    reason=err.reason,
                    deduction_points=err.deduction_points,
                    bbox=err.bbox,
                )
                copied_error.anchor_ids = list(getattr(err, "anchor_ids", []) or [])
                target.errors.append(copied_error)

        result.normalize_scores()

    def _find_matching_sentence(self, result: GradingResult, rule_sa: SentenceAnalysis) -> Optional[SentenceAnalysis]:
        rule_source = self._clean_for_match(rule_sa.original_classical)
        rule_student = self._clean_for_match(rule_sa.student_translation)
        best = None
        best_score = 0.0
        for sa in result.sentence_analyses:
            source = self._clean_for_match(sa.original_classical)
            student = self._clean_for_match(sa.student_translation)
            score = 0.0
            if rule_source and source and (rule_source in source or source in rule_source):
                score += 0.6
            if rule_student and student:
                score += 0.4 * (len(set(rule_student) & set(student)) / max(len(set(rule_student) | set(student)), 1))
            if score > best_score:
                best_score = score
                best = sa
        return best if best_score >= 0.25 else None

    def _is_high_confidence_rule(self, err: ErrorItem) -> bool:
        text = f"{getattr(err.error_type, 'value', err.error_type)} {err.original_text} {err.correct_text} {err.reason}"
        if any(k in text for k in ["主语", "佩环", "珮环", "错字", "不规范", "藤", "飘拂", "俶尔"]):
            return True
        if err.error_type in (ErrorType.TYPO, ErrorType.CONTENT_ERROR, ErrorType.FUNCTION_ERROR):
            return bool(err.bbox and err.original_text and err.correct_text and len(self._clean_for_match(err.original_text)) <= 6)
        return False

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

        if not best_line or best_line_score < 1.0:
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
                return None
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
