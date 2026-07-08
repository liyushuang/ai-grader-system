"""
标注工具函数 — 从 GradingResult 自动生成符号标注数据

规则:
1. 横线：问题句/订正项，短批注放在文字行末。
2. 圆圈：错字/错词/可圈出的具体错误，贴近字词。
3. 波浪线：点睛句，表示值得保留或肯定的表达。
4. 对勾：重点字词翻译正确，轻量正向标记。
"""

from typing import List, Tuple
import sys
sys.path.insert(0, '/workspace/poc_grader')

from grader_base import (
    GradingResult, Annotation, AnnotationType, AnnotationSource,
    SentenceAnalysis, ErrorItem, ErrorType,
)

MAX_SIDE_ANNOTATIONS = 12
MAX_CIRCLE_ANNOTATIONS = 8
MIN_TYPES = ("line", "circle", "wavy", "check")


def generate_annotations_from_result(result: GradingResult) -> List[Annotation]:
    """
    从批改结果自动生成初始标注列表。

    错字类只画红圈；其他问题和点睛句进入编号旁批流。
    """
    circle_candidates: List[Tuple[int, int, SentenceAnalysis, ErrorItem]] = []
    side_error_candidates: List[Tuple[int, int, SentenceAnalysis, ErrorItem]] = []
    wave_candidates: List[Tuple[int, SentenceAnalysis]] = []

    for si, sa in enumerate(result.sentence_analyses):
        for ei, err in enumerate(sa.errors):
            if not err.bbox or not _is_canvas_worthy_error(err):
                continue
            if _should_circle_error(err):
                circle_candidates.append((si, ei, sa, err))
            else:
                side_error_candidates.append((si, ei, sa, err))
        if sa.is_highlight and sa.bbox and not sa.errors:
            wave_candidates.append((si, sa))

    circle_candidates = _dedupe_error_candidates(circle_candidates)
    side_error_candidates = _dedupe_error_candidates(side_error_candidates)
    side_candidates = []
    circle_candidates = sorted(
        circle_candidates,
        key=lambda item: (_error_priority(item[3]), _bbox_area(item[3].bbox)),
        reverse=True,
    )[:MAX_CIRCLE_ANNOTATIONS]

    for si, ei, _sa, err in side_error_candidates:
        if not err.bbox:
            continue
        side_candidates.append({
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
        side_candidates.append({
            "priority": 70 + _highlight_priority(sa),
            "kind_rank": 1,
            "si": si,
            "ei": None,
            "bbox": sa.bbox,
            "build": lambda si=si, sa=sa: _build_wave_annotation(si, sa),
        })

    side_candidates.sort(
        key=lambda item: (
            item["priority"],
            -item["kind_rank"],
            -_bbox_area(item["bbox"]),
        ),
        reverse=True,
    )
    selected_side = sorted(
        side_candidates[:MAX_SIDE_ANNOTATIONS],
        key=lambda item: (item["bbox"].y1 if item["bbox"] else 0, item["bbox"].x1 if item["bbox"] else 0),
    )
    selected_circles = sorted(
        circle_candidates,
        key=lambda item: (item[3].bbox.y1 if item[3].bbox else 0, item[3].bbox.x1 if item[3].bbox else 0),
    )

    annotations: List[Annotation] = []
    for idx, item in enumerate(selected_side, 1):
        ann = item["build"]()
        ann.id = f"ann_{idx:03d}"
        annotations.append(ann)
    for idx, (si, ei, _sa, err) in enumerate(selected_circles, 1):
        ann = _build_error_annotation(si, ei, err)
        ann.id = f"circle_{idx:03d}"
        annotations.append(ann)

    _ensure_minimum_annotation_types(
        annotations,
        result,
        side_error_candidates=side_error_candidates,
        circle_candidates=circle_candidates,
        wave_candidates=wave_candidates,
    )
    _renumber_annotations(annotations)
    return annotations


def _build_error_annotation(si: int, ei: int, err: ErrorItem) -> Annotation:
    eb = err.bbox
    if _should_circle_error(err):
        return _build_circle_annotation(si, ei, err)

    line_y = _underline_y(eb)
    ann = Annotation(
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
    return _attach_error_detail(ann, err)


def _build_circle_annotation(si: int, ei: int, err: ErrorItem) -> Annotation:
    eb = err.bbox
    pad_x = max(6, int(eb.width * 0.18))
    pad_y = max(6, int(eb.height * 0.12))
    ann = Annotation(
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
    return _attach_error_detail(ann, err)


def _attach_error_detail(ann: Annotation, err: ErrorItem) -> Annotation:
    ann.error_type = getattr(err.error_type, "value", err.error_type)
    ann.reason = err.reason or ""
    ann.original_text = err.original_text or ""
    ann.correct_text = err.correct_text or ""
    return ann


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


def _build_check_annotation(si: int, sa: SentenceAnalysis) -> Annotation:
    bbox = sa.bbox
    width = max(28, min(70, int(bbox.width * 0.18)))
    height = max(18, min(42, int(bbox.height * 0.36)))
    x1 = int(bbox.x1 + bbox.width * 0.52)
    y1 = int(bbox.y1 + bbox.height * 0.28)
    return Annotation(
        id="",
        annotation_type=AnnotationType.CHECK,
        start_x=x1,
        start_y=y1,
        end_x=x1 + width,
        end_y=y1 + height,
        source=AnnotationSource.AI,
        sentence_index=si,
        error_index=None,
        comment="翻译准确",
    )


def _ensure_minimum_annotation_types(
    annotations: List[Annotation],
    result: GradingResult,
    side_error_candidates: List[Tuple[int, int, SentenceAnalysis, ErrorItem]],
    circle_candidates: List[Tuple[int, int, SentenceAnalysis, ErrorItem]],
    wave_candidates: List[Tuple[int, SentenceAnalysis]],
) -> None:
    existing = {a.annotation_type.value for a in annotations}

    if "line" not in existing and side_error_candidates:
        si, ei, _sa, err = sorted(side_error_candidates, key=lambda item: _error_priority(item[3]), reverse=True)[0]
        annotations.append(_build_error_annotation(si, ei, err))
        existing.add("line")

    if "circle" not in existing:
        circle_source = circle_candidates[:1] or side_error_candidates[:1]
        if circle_source:
            si, ei, _sa, err = circle_source[0]
            annotations.append(_build_circle_annotation(si, ei, err))
            existing.add("circle")

    if "wavy" not in existing:
        fallback = wave_candidates[:1] or _best_sentence_candidates(result, prefer_clean=True)
        if fallback:
            si, sa = fallback[0]
            annotations.append(_build_wave_annotation(si, sa))
            existing.add("wavy")

    if "check" not in existing:
        fallback = _best_sentence_candidates(result, prefer_clean=True)
        if fallback:
            si, sa = fallback[0]
            annotations.append(_build_check_annotation(si, sa))


def _best_sentence_candidates(result: GradingResult, prefer_clean: bool = False) -> List[Tuple[int, SentenceAnalysis]]:
    candidates = [(si, sa) for si, sa in enumerate(result.sentence_analyses) if sa.bbox]
    if prefer_clean:
        candidates = [(si, sa) for si, sa in candidates if not sa.errors]
        candidates.sort(key=lambda item: (item[1].sentence_score or 0, _highlight_priority(item[1])), reverse=True)
    else:
        candidates.sort(key=lambda item: (item[1].sentence_score or 0, _highlight_priority(item[1])), reverse=True)
    return candidates


def _renumber_annotations(annotations: List[Annotation]) -> None:
    counters = {"ann": 1, "circle": 1, "wavy": 1, "check": 1}
    for ann in annotations:
        typ = ann.annotation_type.value
        if typ == "circle":
            ann.id = ann.id or f"circle_{counters['circle']:03d}"
            counters["circle"] += 1
        elif typ == "wavy":
            ann.id = ann.id or f"wavy_{counters['wavy']:03d}"
            counters["wavy"] += 1
        elif typ == "check":
            ann.id = ann.id or f"check_{counters['check']:03d}"
            counters["check"] += 1
        else:
            ann.id = ann.id or f"ann_{counters['ann']:03d}"
            counters["ann"] += 1


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
    if getattr(err, "model_added", False) and err.bbox:
        return True
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
    if _should_circle_error(err) and err.correct_text:
        return _clip_comment(err.correct_text, 8)
    custom = getattr(err, "teacher_comment", "")
    if custom:
        return _clip_comment(custom, 42)
    if "主语" in text and err.correct_text:
        return _clip_comment(f"补充主语：{err.correct_text}", 30)
    if "错字" in text or "不规范" in text:
        if err.original_text and err.correct_text:
            return _clip_comment(f"{err.original_text}应写作{err.correct_text}", 30)
        if err.correct_text:
            return _clip_comment(f"这里改成{err.correct_text}", 30)
        if err.original_text:
            return _clip_comment(f"圈出错字：{err.original_text}", 30)
    if err.original_text in ("佩环", "珮环") or "佩环" in text or "珮环" in text:
        return _clip_comment("佩环：玉佩玉环相碰撞", 30)
    if "形异" in text:
        return _clip_comment("表达生硬，建议译为“形态各异”", 30)
    if err.original_text and err.correct_text:
        return _clip_comment(f"{err.original_text}→{err.correct_text}", 32)
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
