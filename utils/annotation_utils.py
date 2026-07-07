"""
标注工具函数 — 从 GradingResult 自动生成符号标注数据

规则:
1. is_excellent=True + bbox存在 → 波浪线标注（原始图片y2+20px，Canvas再+12px固定偏移，确保不遮挡）
2. errors[i].bbox存在 → 横线标注（原始图片y2+15px，Canvas再+10px固定偏移，确保不遮挡）
3. is_highlight=True + bbox存在 → 星星标注（句子左上角，偏上15px偏左15px，小星星不遮挡）
"""

from typing import List
import sys
sys.path.insert(0, '/workspace/poc_grader')

from grader_base import (
    GradingResult, Annotation, AnnotationType, AnnotationSource,
    SentenceAnalysis, ErrorItem,
)


def generate_annotations_from_result(result: GradingResult) -> List[Annotation]:
    """
    从批改结果自动生成初始标注列表。

    遍历所有句子分析，根据标记生成对应类型的符号标注。
    """
    annotations: List[Annotation] = []
    ann_counter = 0

    for si, sa in enumerate(result.sentence_analyses):
        # ── 波浪线：精彩句（文字底部下方20px，基础偏移+Canvas固定偏移确保不覆盖）──
        if sa.is_excellent and sa.bbox:
            ann_counter += 1
            b = sa.bbox
            # 波浪线放在文字行底部下方20px（基础偏移，Canvas渲染时再+12px固定偏移）
            wave_y = b.y2 + 20
            annotations.append(Annotation(
                id=f"ann_{ann_counter:03d}",
                annotation_type=AnnotationType.WAVY,
                start_x=b.x1,
                start_y=wave_y,
                end_x=b.x2,
                end_y=wave_y,
                source=AnnotationSource.AI,
                sentence_index=si,
                comment="翻译精彩，表达流畅",
            ))

        # ── 横线：问题句（错误文字底部下方15px，基础偏移+Canvas固定偏移确保不覆盖）──
        for ei, err in enumerate(sa.errors):
            ann_counter += 1
            # 优先使用 error 的 bbox，否则使用 sentence 的 bbox
            eb = err.bbox if err.bbox else sa.bbox
            if not eb:
                continue
            # 横线放在错误文字底部下方15px（基础偏移，Canvas渲染时再+10px固定偏移）
            line_y = eb.y2 + 15
            comment_parts = [f"[{err.error_type.value}]"]
            if err.original_text and err.correct_text:
                comment_parts.append(f"{err.original_text} → {err.correct_text}")
            if err.reason:
                comment_parts.append(err.reason)
            if err.deduction_points:
                comment_parts.append(f"扣{err.deduction_points}分")

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
                comment=": ".join(comment_parts),
            ))

        # ── 星星：点睛句（句子左上角区域，偏上15px偏左15px，避免遮挡文字）──
        if sa.is_highlight and sa.bbox:
            ann_counter += 1
            b = sa.bbox
            # 星星放在句子左上角偏上偏左的位置，避免遮挡文字
            star_x = b.x1 - 15
            star_y = b.y1 - 15
            annotations.append(Annotation(
                id=f"ann_{ann_counter:03d}",
                annotation_type=AnnotationType.STAR,
                start_x=star_x,
                start_y=star_y,
                end_x=star_x,
                end_y=star_y,
                source=AnnotationSource.AI,
                sentence_index=si,
                comment=sa.highlight_comment or f"点睛句: {sa.original_classical}",
            ))

    return annotations


def annotations_to_dict_list(annotations: List[Annotation]) -> List[dict]:
    """将 Annotation 列表转为可 JSON 序列化的字典列表"""
    return [a.to_dict() for a in annotations]


def annotations_from_dict_list(data: List[dict]) -> List[Annotation]:
    """从字典列表还原 Annotation 列表"""
    return [Annotation.from_dict(d) for d in data]
