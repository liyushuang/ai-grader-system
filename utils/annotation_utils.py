"""
标注工具函数 — 从 GradingResult 自动生成符号标注数据

规则:
1. 横线：重点词误译、漏译、主语/句式问题。
2. 圆圈：错字/不规范字。
3. 波浪线：点睛句/重点积累句。
4. 每张图最多 12 条，先按教学优先级筛选，再按图片阅读顺序编号。
"""

from typing import List, Tuple
import sys
sys.path.insert(0, '/workspace/poc_grader')

from grader_base import (
    GradingResult, Annotation, AnnotationType, AnnotationSource,
    SentenceAnalysis, ErrorItem, ErrorType,
)

MAX_AUTO_ANNOTATIONS = 12


def generate_annotations_from_result(result: GradingResult) -> List[Annotation]:
    """
    从批改结果自动生成初始标注列表。

    只保留老师式少量高价值旁批，避免把模型输出全量铺到画面上。
    """
    error_candidates: List[Tuple[int, int, SentenceAnalysis, ErrorItem]] = []
    wave_candidates: List[Tuple[int, SentenceAnalysis]] = []

    for si, sa in enumerate(result.sentence_analyses):
        for ei, err in enumerate(sa.errors):
            if getattr(err, "model_added", False):
                continue
            if err.bbox and _is_canvas_worthy_error(err):
                error_candidates.append((si, ei, sa, err))
        if sa.is_highlight and sa.bbox:
            wave_candidates.append((si, sa))

    error_candidates = _dedupe_error_candidates(error_candidates)
    candidates = []

    for si, ei, _sa, err in error_candidates:
        if not err.bbox:
            continue
        candidates.append({
            "priority": _error_priority(err),
            "kind_rank": 0,
            "si": si,
            "ei": ei,
            "bbox": err.bbox,
            "build": lambda si=si, ei=ei, err=err: _build_error_annotation(si, ei, err),
        })

    for si, sa in wave_candidates:
        if not sa.bbox:
            continue
        candidates.append({
            "priority": 70 + _highlight_priority(sa),
            "kind_rank": 1,
            "si": si,
            "ei": None,
            "bbox": sa.bbox,
            "build": lambda si=si, sa=sa: _build_wave_annotation(si, sa),
        })

    candidates.sort(
        key=lambda item: (
            item["priority"],
            -item["kind_rank"],
            -_bbox_area(item["bbox"]),
        ),
        reverse=True,
    )
    selected = sorted(
        candidates[:MAX_AUTO_ANNOTATIONS],
        key=lambda item: (item["bbox"].y1 if item["bbox"] else 0, item["bbox"].x1 if item["bbox"] else 0),
    )

    annotations: List[Annotation] = []
    for idx, item in enumerate(selected, 1):
        ann = item["build"]()
        ann.id = f"ann_{idx:03d}"
        annotations.append(ann)

    return annotations


def _build_error_annotation(si: int, ei: int, err: ErrorItem) -> Annotation:
    eb = err.bbox
    if _should_circle_error(err):
        pad_x = max(6, int(eb.width * 0.18))
        pad_y = max(6, int(eb.height * 0.12))
        return Annotation(
            id="",
            annotation_type=AnnotationType.CIRCLE,
            start_x=max(0, eb.x1 - pad_x),
            start_y=max(0, eb.y1 - pad_y),
            end_x=eb.x2 + pad_x,
            end_y=eb.y2 + pad_y,
            source=AnnotationSource.AI,
            sentence_index=si,
            error_index=ei,
            comment=_teacher_error_comment(err),
        )

    line_y = _underline_y(eb)
    return Annotation(
        id="",
        annotation_type=AnnotationType.LINE,
        start_x=eb.x1,
        start_y=line_y,
        end_x=eb.x2,
        end_y=line_y,
        source=AnnotationSource.AI,
        sentence_index=si,
        error_index=ei,
        comment=_teacher_error_comment(err),
    )


def _should_circle_error(err: ErrorItem) -> bool:
    text = f"{getattr(err.error_type, 'value', err.error_type)} {err.original_text} {err.correct_text} {err.reason}"
    return (
        err.error_type == ErrorType.TYPO
        or "错字" in text
        or "不规范字" in text
        or "错别字" in text
    )


def _build_wave_annotation(si: int, sa: SentenceAnalysis) -> Annotation:
    bbox = sa.bbox
    y = _underline_y(bbox)
    return Annotation(
        id="",
        annotation_type=AnnotationType.WAVY,
        start_x=bbox.x1,
        start_y=y,
        end_x=bbox.x2,
        end_y=y,
        source=AnnotationSource.AI,
        sentence_index=si,
        error_index=None,
        comment=_teacher_highlight_comment(sa),
    )


def _error_priority(err: ErrorItem) -> int:
    text = f"{getattr(err.error_type, 'value', err.error_type)} {err.original_text} {err.correct_text} {err.reason}"
    if any(k in text for k in ["以为", "过清", "可", "许", "斗折", "蛇行", "犬牙", "凄神寒骨", "悄怆幽邃", "空游", "佩环", "珮环"]):
        return 100
    if err.error_type in (ErrorType.OMISSION, ErrorType.CONTENT_ERROR, ErrorType.FUNCTION_ERROR):
        return 90 + int(err.deduction_points or 0)
    if "主语" in text:
        return 86
    if "错字" in text or "不规范" in text or ("字" in text and any(k in text for k in ["藤", "飘", "俶", "佩"])):
        return 82
    priority = {
        ErrorType.TYPO: 70,
        ErrorType.WORD_ORDER: 65,
        ErrorType.ADDITION: 55,
        ErrorType.PUNCTUATION: 0,
    }
    return priority.get(err.error_type, 0)


def _is_canvas_worthy_error(err: ErrorItem) -> bool:
    text = f"{getattr(err.error_type, 'value', err.error_type)} {err.original_text} {err.correct_text} {err.reason}"
    if "主语" in text:
        return True
    if "佩环" in text or "珮环" in text:
        return True
    if err.error_type in (ErrorType.OMISSION, ErrorType.CONTENT_ERROR, ErrorType.FUNCTION_ERROR, ErrorType.WORD_ORDER):
        return True
    if "错字" in text or "不规范" in text:
        return True
    if err.error_type in (ErrorType.TYPO, ErrorType.CONTENT_ERROR) and err.original_text and err.correct_text:
        return True
    return False


def _dedupe_error_candidates(candidates: List[Tuple[int, int, SentenceAnalysis, ErrorItem]]) -> List[Tuple[int, int, SentenceAnalysis, ErrorItem]]:
    result = []
    seen = set()
    for item in candidates:
        _, _, _, err = item
        text = f"{err.original_text}{err.correct_text}{err.reason}"
        if "佩环" in text or "珮环" in text:
            key = "佩环"
        elif "主语" in text:
            key = f"主语:{err.correct_text or err.original_text}"
        else:
            key = f"{getattr(err.error_type, 'value', err.error_type)}:{err.original_text}:{err.correct_text}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _bbox_area(bbox) -> int:
    if not bbox:
        return 0
    return max(0, bbox.x2 - bbox.x1) * max(0, bbox.y2 - bbox.y1)


def _underline_y(bbox) -> int:
    """Place underline near the handwritten baseline, not at Baidu's loose bbox bottom."""
    height = max(1, bbox.y2 - bbox.y1)
    return int(bbox.y1 + height * 0.68) + 4


def _highlight_priority(sa: SentenceAnalysis) -> int:
    key_phrases = [
        "心乐之",
        "全石以为底",
        "潭中鱼可百许头",
        "青树翠蔓",
        "凄神寒骨",
    ]
    for idx, phrase in enumerate(key_phrases):
        if phrase in sa.original_classical:
            return len(key_phrases) - idx
    return 0


def _clip_comment(text: str, limit: int = 28) -> str:
    text = " ".join((text or "").replace("\n", " ").split())
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"


def _teacher_error_comment(err: ErrorItem) -> str:
    text = f"{getattr(err.error_type, 'value', err.error_type)} {err.original_text} {err.correct_text} {err.reason}"
    if "主语" in text and err.correct_text:
        return _clip_comment(f"补充主语：{err.correct_text}", 30)
    if "错字" in text or "不规范" in text:
        if err.original_text:
            return _clip_comment(f"错字：{err.original_text}", 30)
    if err.original_text in ("佩环", "珮环") or "佩环" in text or "珮环" in text:
        return _clip_comment("佩环：玉佩玉环相碰撞", 30)
    if err.original_text and err.correct_text:
        return _clip_comment(f"改：{err.original_text}→{err.correct_text}")
    if err.reason:
        return _clip_comment(f"需订正：{err.reason}")
    return _clip_comment(f"需订正：{err.error_type.value}")


def _teacher_highlight_comment(sa: SentenceAnalysis) -> str:
    if sa.highlight_comment:
        text = sa.highlight_comment
        if not text.startswith("点睛句"):
            text = f"点睛句：{text}"
        return _clip_comment(text, 30)
    return _clip_comment("点睛句：关键画面译得准", 30)


def annotations_to_dict_list(annotations: List[Annotation]) -> List[dict]:
    """将 Annotation 列表转为可 JSON 序列化的字典列表"""
    return [a.to_dict() for a in annotations]


def annotations_from_dict_list(data: List[dict]) -> List[Annotation]:
    """从字典列表还原 Annotation 列表"""
    return [Annotation.from_dict(d) for d in data]
