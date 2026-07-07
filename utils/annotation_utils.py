"""
标注工具函数 — 从 GradingResult 自动生成符号标注数据

规则:
1. is_excellent=True + bbox存在 → 波浪线标注（原始图片y2+20px，Canvas再+12px固定偏移，确保不遮挡）
2. errors[i].bbox存在 → 横线标注（原始图片y2+15px，Canvas再+10px固定偏移，确保不遮挡）
3. is_highlight=True + bbox存在 → 星星标注（句子左上角，偏上15px偏左15px，小星星不遮挡）
"""

from typing import List, Tuple
import sys
sys.path.insert(0, '/workspace/poc_grader')

from grader_base import (
    GradingResult, Annotation, AnnotationType, AnnotationSource,
    SentenceAnalysis, ErrorItem, ErrorType,
)


def generate_annotations_from_result(result: GradingResult) -> List[Annotation]:
    """
    从批改结果自动生成初始标注列表。

    只保留老师式少量高价值旁批，避免把模型输出全量铺到画面上。
    """
    annotations: List[Annotation] = []
    ann_counter = 0

    error_candidates: List[Tuple[int, int, SentenceAnalysis, ErrorItem]] = []
    star_candidates: List[Tuple[int, SentenceAnalysis]] = []
    wave_candidates: List[Tuple[int, SentenceAnalysis]] = []

    for si, sa in enumerate(result.sentence_analyses):
        for ei, err in enumerate(sa.errors):
            if err.bbox or sa.bbox:
                error_candidates.append((si, ei, sa, err))
        if sa.is_highlight and sa.bbox:
            star_candidates.append((si, sa))
        if sa.is_excellent and sa.bbox and not sa.errors:
            wave_candidates.append((si, sa))

    error_candidates.sort(
        key=lambda item: (
            item[3].deduction_points,
            _error_priority(item[3]),
            1 if item[3].bbox else 0,
        ),
        reverse=True,
    )

    for si, ei, sa, err in error_candidates[:6]:
        eb = err.bbox if err.bbox else sa.bbox
        if not eb:
            continue
        ann_counter += 1
        line_y = eb.y2 + 4
        annotations.append(Annotation(
            id=f"ann_{ann_counter:03d}",
            annotation_type=AnnotationType.LINE,
            start_x=eb.x1,
            start_y=line_y,
            end_x=eb.x2,
            end_y=line_y,
            source=AnnotationSource.AI,
            sentence_index=si,
            error_index=ei,
            comment=_teacher_error_comment(err),
        ))

    star_candidates.sort(key=lambda item: _highlight_priority(item[1]), reverse=True)
    for si, sa in star_candidates[:2]:
        if len(annotations) >= 9:
            break
        ann_counter += 1
        b = sa.bbox
        star_x = max(0, b.x1 - 18)
        star_y = max(0, b.y1 - 12)
        annotations.append(Annotation(
            id=f"ann_{ann_counter:03d}",
            annotation_type=AnnotationType.STAR,
            start_x=star_x,
            start_y=star_y,
            end_x=star_x,
            end_y=star_y,
            source=AnnotationSource.AI,
            sentence_index=si,
            comment=_teacher_star_comment(sa),
        ))

    for si, sa in wave_candidates[:1]:
        if len(annotations) >= 10:
            break
        ann_counter += 1
        b = sa.bbox
        wave_y = b.y2 + 4
        annotations.append(Annotation(
            id=f"ann_{ann_counter:03d}",
            annotation_type=AnnotationType.WAVY,
            start_x=b.x1,
            start_y=wave_y,
            end_x=b.x2,
            end_y=wave_y,
            source=AnnotationSource.AI,
            sentence_index=si,
            comment=_teacher_wave_comment(sa),
        ))

    return annotations


def _error_priority(err: ErrorItem) -> int:
    text = f"{getattr(err.error_type, 'value', err.error_type)} {err.original_text} {err.correct_text} {err.reason}"
    if "主语" in text:
        return 8
    if "错字" in text or "不规范" in text or "字" in text and any(k in text for k in ["藤", "飘", "俶", "佩"]):
        return 7
    priority = {
        ErrorType.TYPO: 6,
        ErrorType.OMISSION: 5,
        ErrorType.CONTENT_ERROR: 5,
        ErrorType.WORD_ORDER: 3,
        ErrorType.FUNCTION_ERROR: 3,
        ErrorType.ADDITION: 2,
        ErrorType.PUNCTUATION: 0,
    }
    return priority.get(err.error_type, 0)


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


def _teacher_star_comment(sa: SentenceAnalysis) -> str:
    if sa.highlight_comment:
        text = sa.highlight_comment
        if not text.startswith("点睛句"):
            text = f"点睛句：{text}"
        return _clip_comment(text, 30)
    return _clip_comment("点睛句：关键画面译得准", 30)


def _teacher_wave_comment(sa: SentenceAnalysis) -> str:
    if sa.highlight_comment:
        return _clip_comment(sa.highlight_comment, 26)
    return "好句：翻译准确流畅"


def annotations_to_dict_list(annotations: List[Annotation]) -> List[dict]:
    """将 Annotation 列表转为可 JSON 序列化的字典列表"""
    return [a.to_dict() for a in annotations]


def annotations_from_dict_list(data: List[dict]) -> List[Annotation]:
    """从字典列表还原 Annotation 列表"""
    return [Annotation.from_dict(d) for d in data]
