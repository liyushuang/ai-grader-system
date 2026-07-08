"""
PoC 框架 — 抽象基类定义

所有批改方案（Qwen-VL-Max / Gemini / 百度API 等）都实现此接口，
通过 GradingStrategy 基类的抽象方法保证可插拔切换。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum
import uuid
from datetime import datetime, timezone


# ── 枚举定义 ─────────────────────────────────────────

class ErrorType(str, Enum):
    """错误类型枚举"""
    CONTENT_ERROR = "实词错误"       # 实词翻译错误
    FUNCTION_ERROR = "虚词错误"     # 虚词翻译错误
    OMISSION = "漏译"               # 遗漏未译
    ADDITION = "多译"               # 添加了原文没有的内容
    TYPO = "错别字"                 # 手写错别字
    WORD_ORDER = "语序错误"         # 句式/语序问题
    PUNCTUATION = "标点错误"        # 标点符号问题


class AnnotationType(str, Enum):
    """符号标注类型"""
    WAVY = "wavy"        # 点睛句 — 波浪线呈现
    LINE = "line"        # 横线 — 问题句
    CIRCLE = "circle"    # 圆圈 — 错字/错词
    STAR = "star"        # 已废弃：旧数据兼容为 wavy
    CHECK = "check"      # 对勾 — 重点字词翻译正确


class AnnotationSource(str, Enum):
    """标注来源"""
    AI = "ai"            # AI自动生成
    TEACHER = "teacher"  # 教师人工添加/修改


class Confidence(str, Enum):
    """置信度等级"""
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class GradingStatus(str, Enum):
    """批改状态"""
    SUCCESS = "success"
    LOW_CONFIDENCE = "low_confidence"   # 成功但置信度低，建议人工复核
    IMAGE_QUALITY_POOR = "image_poor"   # 图片质量差，无法批改
    PROCESSING_ERROR = "error"          # 处理异常
    TIMEOUT = "timeout"                 # 超时


# ── 数据类 — 批改结果的结构化定义 ──────────────────────

@dataclass
class BoundingBox:
    """包围盒：标注错误在图片中的位置"""
    x1: int
    y1: int
    x2: int
    y2: int

    @classmethod
    def from_list(cls, bbox: list) -> "BoundingBox":
        if not bbox or len(bbox) != 4:
            return None
        return cls(x1=int(bbox[0]), y1=int(bbox[1]),
                   x2=int(bbox[2]), y2=int(bbox[3]))

    def to_list(self) -> list:
        return [self.x1, self.y1, self.x2, self.y2]

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class ErrorItem:
    """单个批改错误项"""
    error_type: ErrorType
    original_text: str              # 学生写的错误内容
    correct_text: str               # 应该的正确内容
    reason: str                     # 判定理由
    deduction_points: int           # 扣分
    bbox: Optional[BoundingBox] = None   # 错误位置（可选，无Grounding方案可为None）


@dataclass
class SentenceAnalysis:
    """逐句分析结果"""
    original_classical: str         # 对应文言文原文
    student_translation: str        # 学生译文
    standard_translation: str       # 标准译文
    errors: List[ErrorItem] = field(default_factory=list)
    sentence_score: int = 0         # 该句得分
    is_excellent: bool = False      # 是否翻译精彩（零错误且表达好）
    is_highlight: bool = False      # 是否为点睛句（★标注）
    highlight_comment: str = ""     # 点睛句赏析说明
    polished_translation: str = ""  # 润色后译文
    bbox: Optional[BoundingBox] = None  # 该句在图片中的区域


@dataclass
class Annotation:
    """单个符号标注 — 对应波浪线/横线/星星"""
    id: str                                          # 唯一ID
    annotation_type: AnnotationType                  # 标注类型

    # 位置 (像素坐标，基于原图)
    start_x: int
    start_y: int
    end_x: int
    end_y: int

    # 关联信息
    source: AnnotationSource = AnnotationSource.AI
    sentence_index: Optional[int] = None             # 关联的句子索引
    error_index: Optional[int] = None                # 关联的错误索引（仅横线）

    # 批注文字
    comment: str = ""

    # 元信息
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "ai"

    def __post_init__(self):
        if not self.id:
            self.id = f"ann_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "type": self.annotation_type.value,
            "start_x": self.start_x,
            "start_y": self.start_y,
            "end_x": self.end_x,
            "end_y": self.end_y,
            "source": self.source.value,
            "sentence_index": self.sentence_index,
            "error_index": self.error_index,
            "comment": self.comment,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
        }
        for key in ("error_type", "reason", "original_text", "correct_text"):
            value = getattr(self, key, None)
            if value:
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, d: dict) -> "Annotation":
        ann = cls(
            id=d.get("id", ""),
            annotation_type=AnnotationType(d["type"]),
            start_x=d["start_x"],
            start_y=d["start_y"],
            end_x=d["end_x"],
            end_y=d["end_y"],
            source=AnnotationSource(d.get("source", "ai")),
            sentence_index=d.get("sentence_index"),
            error_index=d.get("error_index"),
            comment=d.get("comment", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            created_by=d.get("created_by", "ai"),
        )
        for key in ("error_type", "reason", "original_text", "correct_text"):
            if d.get(key):
                setattr(ann, key, d.get(key))
        return ann

def _clamp_int(value, low: int, high: int) -> int:
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


@dataclass
class GradingResult:
    """完整的批改结果"""
    # 核心结果
    recognized_text: str                    # 识别到的学生完整作答文字
    sentence_analyses: List[SentenceAnalysis] = field(default_factory=list)
    total_score: int = 0                    # 总分(0-100)
    overall_comment: str = ""               # 总体评语
    overall_comment_general: str = ""       # 通用风格评语
    overall_comment_encouraging: str = ""   # 加油鼓励风评语
    overall_comment_instructive: str = ""    # 严厉指导风评语
    polished_full_translation: str = ""     # 全文润色译文

    # 元信息
    confidence: Confidence = Confidence.MEDIUM
    status: GradingStatus = GradingStatus.SUCCESS
    error_message: str = ""                 # 异常时记录错误信息

    # 性能信息
    processing_time_ms: int = 0             # 处理耗时(毫秒)
    token_usage: dict = field(default_factory=dict)  # token消耗统计

    # 调试信息
    raw_response: str = ""                  # 模型原始响应
    grader_name: str = ""                   # 使用的批改器名称

    # ── 增强批改字段（按《小石潭记批改要求》）─────────
    homework_completion: str = ""           # 作业完成情况描述
    strengths: List[str] = field(default_factory=list)     # 优点（2-4条）
    weaknesses: List[str] = field(default_factory=list)    # 问题（1-4条）
    suggestions: List[str] = field(default_factory=list)   # 修改建议
    highlight_sentences: List[dict] = field(default_factory=list)  # 点睛句积累
    parent_feedback: str = ""               # 家长反馈话术
    system_tags: List[str] = field(default_factory=list)   # 系统标签
    dimension_scores: dict = field(default_factory=lambda: {
        "完整度": 0, "准确度": 0, "重点词掌握": 0,
        "句式处理": 0, "表达流畅度": 0, "忠实原文": 0,
    })
    dimension_analysis: dict = field(default_factory=dict)  # 各维度详细分析 {"维度名": {"strength":"...", "weakness":"..."}}

    # ── 标注数据（符号标注渲染 + 人工编辑）─────────
    annotations: List[Annotation] = field(default_factory=list)
    annotation_version: int = 1

    @property
    def total_errors(self) -> int:
        return sum(len(sa.errors) for sa in self.sentence_analyses)

    @property
    def total_deductions(self) -> int:
        return sum(
            e.deduction_points
            for sa in self.sentence_analyses
            for e in sa.errors
        )

    def normalize_scores(self) -> "GradingResult":
        """Clamp all public scores to their declared ranges."""
        self.total_score = _clamp_int(self.total_score, 0, 100)
        for sa in self.sentence_analyses:
            sa.sentence_score = _clamp_int(sa.sentence_score, 0, 100)
            for err in sa.errors:
                err.deduction_points = _clamp_int(err.deduction_points, 0, 100)

        normalized = {}
        for name, score in (self.dimension_scores or {}).items():
            normalized[name] = _clamp_int(score, 0, 20)
        self.dimension_scores = normalized
        return self

    @property
    def has_bbox(self) -> bool:
        """是否有坐标信息（决定能否渲染红圈）"""
        return any(
            e.bbox is not None
            for sa in self.sentence_analyses
            for e in sa.errors
        )

    def summary(self) -> str:
        return (
            f"[{self.grader_name}] "
            f"得分:{self.total_score} "
            f"错误:{self.total_errors}处 "
            f"扣分:{self.total_deductions}分 "
            f"置信度:{self.confidence.value} "
            f"耗时:{self.processing_time_ms}ms"
        )


# ── 输入/输出结构 ─────────────────────────────────────

@dataclass
class GradingInput:
    """批改输入"""
    image_path: str                 # 图片文件路径
    image_data: Optional[bytes] = None      # 图片二进制数据（与path二选一）
    textbook_name: str = "小石潭记"          # 课文名称
    textbook_author: str = "柳宗元"          # 作者
    # 以下是可选的附加上下文
    classical_text: Optional[str] = None     # 文言文原文全文
    standard_translation: Optional[str] = None  # 标准译文
    grading_rules: Optional[dict] = None     # 自定义批改规则（覆盖默认）


@dataclass
class GradingOutput:
    """批改输出（文件级）"""
    result: GradingResult
    annotated_image_path: Optional[str] = None  # 批改完成图路径（如有渲染）
    json_report_path: Optional[str] = None      # JSON 报告路径


# ── 抽象策略接口 ─────────────────────────────────────

class GradingStrategy(ABC):
    """
    批改策略抽象基类

    所有批改方案（Qwen-VL-Max / Gemini / 百度API 等）都必须实现此接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称（用于日志和结果标识）"""
        ...

    @property
    @abstractmethod
    def supports_bbox(self) -> bool:
        """是否支持输出坐标（Grounding能力）"""
        ...

    @abstractmethod
    def grade(self, grading_input: GradingInput) -> GradingResult:
        """
        执行批改，返回结构化结果。

        Args:
            grading_input: 包含图片路径和课文信息的输入对象

        Returns:
            GradingResult: 批改结果（含识别文字、错误列表、总分等）

        Raises:
            GradingException: 批改失败（网络/API/解析异常）
        """
        ...

    def validate(self) -> Tuple[bool, str]:
        """
        验证当前策略是否可用（API Key配置、网络连通等）
        返回 (是否可用, 不可用原因)
        """
        return True, ""

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name}>"


# ── 统一异常类 ────────────────────────────────────────

class GradingException(Exception):
    """批改异常基类"""
    def __init__(self, message: str, grader_name: str = "", cause: Exception = None):
        super().__init__(message)
        self.grader_name = grader_name
        self.cause = cause


class ImageQualityException(GradingException):
    """图片质量不合格"""
    pass


class APIException(GradingException):
    """API调用异常"""
    pass


class ParseException(GradingException):
    """结果解析异常"""
    pass
