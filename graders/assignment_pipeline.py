"""
阶段化批改管线基础模块。

职责：
1. 将 OCR 行清洗为稳定的正文行。
2. 根据当前作业标准生成批改单元。
3. 将 OCR 行按顺序对齐到批改单元。

该模块不调用模型，也不依赖固定 OCR 行数。
"""

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional

from grader_base import BoundingBox


def clean_text(text: str) -> str:
    return re.sub(r"[，。、；：！？\s,.\!\?\;\:\-☰]", "", text or "")


@dataclass
class OCRCharAnchor:
    anchor_id: str
    text: str
    line_no: int
    char_index: int
    bbox: BoundingBox

    def to_dict(self) -> dict:
        return {
            "anchor_id": self.anchor_id,
            "text": self.text,
            "line_no": self.line_no,
            "char_index": self.char_index,
            "bbox": self.bbox.to_list() if self.bbox else None,
        }


@dataclass
class OCRLineView:
    line_no: int
    text: str
    clean_text: str
    bbox: BoundingBox
    char_anchors: List[OCRCharAnchor] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "line_no": self.line_no,
            "text": self.text,
            "clean_text": self.clean_text,
            "bbox": self.bbox.to_list() if self.bbox else None,
            "char_anchors": [anchor.to_dict() for anchor in self.char_anchors],
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }

    def anchor_span_for_text(self, text: str, prefer_last: bool = False) -> tuple:
        """Return (anchor_ids, bbox) for an exact cleaned text span in this OCR line."""
        target = clean_text(text)
        if not target or not self.char_anchors:
            return [], None

        clean_chars = []
        clean_to_anchor_idx = []
        for idx, anchor in enumerate(self.char_anchors):
            cleaned = clean_text(anchor.text)
            if not cleaned:
                continue
            for ch in cleaned:
                clean_chars.append(ch)
                clean_to_anchor_idx.append(idx)

        clean_line = "".join(clean_chars)
        start = clean_line.rfind(target) if prefer_last else clean_line.find(target)
        if start < 0:
            return [], None
        end = start + len(target)
        anchor_indexes = clean_to_anchor_idx[start:end]
        anchors = [self.char_anchors[i] for i in anchor_indexes]
        return [a.anchor_id for a in anchors], bbox_from_anchors(anchors)


def bbox_from_anchors(anchors: List[OCRCharAnchor]) -> Optional[BoundingBox]:
    anchors = [anchor for anchor in anchors if anchor.bbox]
    if not anchors:
        return None
    return BoundingBox(
        min(anchor.bbox.x1 for anchor in anchors),
        min(anchor.bbox.y1 for anchor in anchors),
        max(anchor.bbox.x2 for anchor in anchors),
        max(anchor.bbox.y2 for anchor in anchors),
    )


@dataclass
class AssignmentSegment:
    segment_id: int
    source: str
    reference: str
    anchors: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    segment_type: str = "translation"

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "source": self.source,
            "reference": self.reference,
            "anchors": self.anchors,
            "keywords": self.keywords,
            "segment_type": self.segment_type,
        }


@dataclass
class AlignedSegment:
    segment: AssignmentSegment
    lines: List[OCRLineView] = field(default_factory=list)
    student_text: str = ""
    confidence: float = 0.0
    coverage_ratio: float = 0.0
    visible_reference_start: Optional[int] = None
    visible_reference_end: Optional[int] = None
    needs_review: bool = False
    match_reasons: List[str] = field(default_factory=list)

    @property
    def bbox(self) -> Optional[BoundingBox]:
        lines = [line for line in self.lines if line.bbox]
        if not lines:
            return None
        return BoundingBox(
            min(line.bbox.x1 for line in lines),
            min(line.bbox.y1 for line in lines),
            max(line.bbox.x2 for line in lines),
            max(line.bbox.y2 for line in lines),
        )

    @property
    def line_nos(self) -> List[int]:
        return [line.line_no for line in self.lines]

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment.segment_id,
            "source": self.segment.source,
            "reference": self.segment.reference,
            "student_text": self.student_text,
            "line_nos": self.line_nos,
            "bbox": self.bbox.to_list() if self.bbox else None,
            "confidence": round(self.confidence, 3),
            "coverage_ratio": round(self.coverage_ratio, 3),
            "visible_reference_start": self.visible_reference_start,
            "visible_reference_end": self.visible_reference_end,
            "needs_review": self.needs_review,
            "match_reasons": self.match_reasons,
        }


class AssignmentSegmenter:
    """根据当前作业生成动态批改单元。"""

    def __init__(self, textbook_name: str = "小石潭记", grading_rules: Optional[dict] = None):
        self.textbook_name = textbook_name or "小石潭记"
        self.grading_rules = grading_rules or {}

    def build_segments(self) -> List[AssignmentSegment]:
        custom = self.grading_rules.get("segments") if isinstance(self.grading_rules, dict) else None
        if custom:
            return [
                AssignmentSegment(
                    segment_id=int(item.get("segment_id", idx + 1)),
                    source=item.get("source", ""),
                    reference=item.get("reference", ""),
                    anchors=item.get("anchors", []),
                    keywords=item.get("keywords", []),
                    segment_type=item.get("segment_type", "translation"),
                )
                for idx, item in enumerate(custom)
            ]
        return build_xiaoshitanji_segments()


class OCRCleaner:
    META_PATTERNS = [
        re.compile(r"豆伴匠|豆神教育|DouShen|Doushen", re.I),
        re.compile(r"姓名|班级|日期|分数|教师点评|师点评"),
        re.compile(r"^小石潭记$"),
    ]

    def clean_lines(self, ocr_lines: List[object]) -> List[OCRLineView]:
        cleaned: List[OCRLineView] = []
        for idx, line in enumerate(ocr_lines, 1):
            text = (getattr(line, "text", "") or "").strip()
            text = re.sub(r"☰+", "", text)
            clean = clean_text(text)
            skipped, reason = self._should_skip(text, clean)
            cleaned.append(OCRLineView(
                line_no=idx,
                text=text,
                clean_text=clean,
                bbox=getattr(line, "bbox", None),
                char_anchors=self._build_char_anchors(idx, text, getattr(line, "bbox", None)),
                skipped=skipped,
                skip_reason=reason,
            ))
        return cleaned

    def _build_char_anchors(self, line_no: int, text: str, bbox: BoundingBox) -> List[OCRCharAnchor]:
        if not text or not bbox:
            return []
        chars = [ch for ch in text if not ch.isspace()]
        if not chars:
            return []
        width = max(1, bbox.x2 - bbox.x1)
        anchors: List[OCRCharAnchor] = []
        total = len(chars)
        for idx, ch in enumerate(chars):
            x1 = bbox.x1 + int(width * idx / total)
            x2 = bbox.x1 + int(width * (idx + 1) / total)
            if x2 <= x1:
                x2 = x1 + 1
            anchors.append(OCRCharAnchor(
                anchor_id=f"l{line_no}_c{idx}",
                text=ch,
                line_no=line_no,
                char_index=idx,
                bbox=BoundingBox(x1, bbox.y1, x2, bbox.y2),
            ))
        return anchors

    def body_lines(self, ocr_lines: List[object]) -> List[OCRLineView]:
        return [line for line in self.clean_lines(ocr_lines) if not line.skipped]

    def _should_skip(self, text: str, clean: str) -> tuple:
        if not clean:
            return True, "empty"
        for pattern in self.META_PATTERNS:
            if pattern.search(text):
                return True, "meta"
        if len(clean) <= 2 and not any(ch in clean for ch in "鱼潭竹树"):
            return True, "too_short"
        return False, ""


class AlignmentEngine:
    """把 OCR 正文行按顺序归属到动态作业单元。"""

    def __init__(self, min_confidence: float = 0.18, weak_confidence: float = 0.06):
        self.min_confidence = min_confidence
        self.weak_confidence = weak_confidence

    def align(self, lines: List[OCRLineView], segments: List[AssignmentSegment]) -> List[AlignedSegment]:
        if not segments:
            return []
        groups: Dict[int, List[OCRLineView]] = {seg.segment_id: [] for seg in segments}
        reasons: Dict[int, List[str]] = {seg.segment_id: [] for seg in segments}

        current_idx = 0
        for line in lines:
            best_idx, best_score, best_reasons = self._best_segment_for_line(line, segments, current_idx)
            if best_idx is None:
                best_idx = current_idx
                best_reasons = [f"low_confidence:{best_score:.2f}"]
            elif best_score < self.weak_confidence:
                best_idx = current_idx
                best_reasons = [f"low_confidence:{best_score:.2f}"]
            current_idx = max(current_idx, best_idx)
            groups[segments[current_idx].segment_id].append(line)
            reasons[segments[current_idx].segment_id].extend(best_reasons[:2])

        aligned: List[AlignedSegment] = []
        for idx, seg in enumerate(segments):
            seg_lines = groups.get(seg.segment_id, [])
            student_text = "".join(line.text for line in seg_lines)
            confidence = self._segment_confidence(seg_lines, seg)
            coverage_ratio, visible_start, visible_end = self._segment_coverage(seg_lines, seg)
            aligned.append(AlignedSegment(
                segment=seg,
                lines=seg_lines,
                student_text=student_text,
                confidence=confidence,
                coverage_ratio=coverage_ratio,
                visible_reference_start=visible_start,
                visible_reference_end=visible_end,
                needs_review=(bool(seg_lines) and confidence < self.min_confidence) or not seg_lines,
                match_reasons=list(dict.fromkeys(reasons.get(seg.segment_id, [])))[:5],
            ))
        return self._merge_sparse_segments(aligned)

    def _best_segment_for_line(
        self,
        line: OCRLineView,
        segments: List[AssignmentSegment],
        current_idx: int,
    ) -> tuple:
        candidates = range(current_idx, len(segments))
        scored = []
        for idx in candidates:
            score, reasons = self._line_segment_score(line, segments[idx])
            scored.append((score, idx, reasons))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return None, 0.0, []
        score, idx, reasons = scored[0]
        return idx, score, reasons

    def _line_segment_score(self, line: OCRLineView, segment: AssignmentSegment) -> tuple:
        text = line.clean_text
        if not text:
            return 0.0, []

        anchors = [clean_text(a) for a in segment.anchors if clean_text(a)]
        keywords = [clean_text(k) for k in segment.keywords if clean_text(k)]
        reference = clean_text(segment.reference)
        source = clean_text(segment.source)

        reasons = []
        anchor_hits = [a for a in anchors if a and a in text]
        keyword_hits = [k for k in keywords if k and k in text]

        score = 0.0
        if anchors:
            score += 0.55 * (len(anchor_hits) / len(anchors))
        if keywords:
            score += 0.20 * (len(keyword_hits) / len(keywords))
        if reference:
            overlap = len(set(text) & set(reference)) / max(len(set(text) | set(reference)), 1)
            score += 0.20 * overlap
        if source:
            source_overlap = len(set(text) & set(source)) / max(len(set(text) | set(source)), 1)
            score += 0.05 * source_overlap

        if anchor_hits:
            reasons.append("anchors:" + ",".join(anchor_hits[:4]))
        if keyword_hits:
            reasons.append("keywords:" + ",".join(keyword_hits[:4]))
        return score, reasons

    def _segment_confidence(self, lines: List[OCRLineView], segment: AssignmentSegment) -> float:
        if not lines:
            return 0.0
        text = OCRCleanerText.join_lines(lines)
        pseudo_line = OCRLineView(0, text, clean_text(text), None)
        score, _ = self._line_segment_score(pseudo_line, segment)
        return min(1.0, score)

    def _segment_coverage(self, lines: List[OCRLineView], segment: AssignmentSegment) -> tuple:
        """估算当前图片覆盖了该批改单元的哪一段，避免跨页上传时误判前半句漏译。"""
        if not lines:
            return 0.0, None, None

        student = clean_text(OCRCleanerText.join_lines(lines))
        reference = clean_text(segment.reference)
        if not student or not reference:
            return 0.0, None, None

        markers = [
            clean_text(item)
            for item in (segment.anchors + segment.keywords + [segment.source, segment.reference])
            if clean_text(item)
        ]
        hits = []
        for marker in markers:
            if len(marker) < 2:
                continue
            if marker in student:
                pos = reference.find(marker)
                if pos >= 0:
                    hits.append((pos, pos + len(marker)))

        # 部分锚点来自参考译文的短语；再用学生文本的2-4字窗口在参考译文里找可见范围。
        for size in (4, 3, 2):
            if hits:
                break
            for i in range(max(0, len(student) - size + 1)):
                frag = student[i:i + size]
                if len(frag) < size:
                    continue
                pos = reference.find(frag)
                if pos >= 0:
                    hits.append((pos, pos + size))

        if not hits:
            approx = min(1.0, len(student) / max(len(reference), 1))
            return approx, None, None

        start = min(item[0] for item in hits)
        end = max(item[1] for item in hits)
        span_ratio = max(0.0, (end - start) / max(len(reference), 1))
        length_ratio = min(1.0, len(student) / max(len(reference), 1))
        return max(span_ratio, min(length_ratio, 1.0)), start, end

    def _merge_sparse_segments(self, aligned: List[AlignedSegment]) -> List[AlignedSegment]:
        # 当前保持固定 segment 列表，后续可在这里做跨行拆分/合并策略。
        return aligned


class OCRCleanerText:
    @staticmethod
    def join_lines(lines: List[OCRLineView]) -> str:
        return "".join(line.text for line in lines)


def build_xiaoshitanji_segments() -> List[AssignmentSegment]:
    from rule_engine import _STANDARD_SENTENCES

    anchor_map = {
        1: ["竹林", "水流", "水声", "佩环", "开心", "高兴"],
        2: ["砍", "竹子", "小路", "小潭", "清澈", "清冽"],
        3: ["整块石头", "岸边", "卷起", "露出水面", "石礁", "岛屿", "石岩", "全石", "以为底", "坻", "屿", "嵁", "岩"],
        4: ["藤蔓", "互相遮掩", "遮蔽", "缠绕", "摇动", "下垂", "参差", "飘拂", "飘浮", "翠绿"],
        5: ["一百", "大约", "鱼", "清澈", "潭水", "无水依托", "没有依托", "空中", "游来游去"],
        6: ["日光", "阳光", "影子", "水底", "石头", "不动", "突然", "俶尔", "翕忽", "远处", "游回来", "来来往往", "游客"],
        7: ["西南", "北斗星", "曲折", "蛇", "蜿蜒", "时隐时现"],
        8: ["狗", "牙齿", "互相交错", "参差", "犬牙", "源头"],
        9: ["坐在石潭", "竹子", "树", "环绕", "没有人声", "凄凉", "寒气", "幽静", "忧伤"],
        10: ["太过", "冷静", "冷清", "凄清", "不可停留", "久留", "记下", "离开"],
        11: ["吴武陵", "龚古", "弟弟", "宗玄", "姓崔", "年轻人", "恕己", "奉壹"],
    }

    return [
        AssignmentSegment(
            segment_id=idx + 1,
            source=item["classical"],
            reference=item["translation"],
            anchors=anchor_map.get(idx + 1, []),
            keywords=item.get("keywords", []),
            segment_type="classical_translation",
        )
        for idx, item in enumerate(_STANDARD_SENTENCES)
    ]


def pipeline_debug_dict(
    raw_ocr_lines: List[object],
    clean_lines: List[OCRLineView],
    segments: List[AssignmentSegment],
    aligned: List[AlignedSegment],
) -> dict:
    return {
        "ocr": {
            "line_count": len(raw_ocr_lines),
            "lines": [line.to_dict() for line in clean_lines],
        },
        "segments": [seg.to_dict() for seg in segments],
        "alignment": [item.to_dict() for item in aligned],
    }
