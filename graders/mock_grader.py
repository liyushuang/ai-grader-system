"""
Mock Grader — 模拟批改器（无需API即可跑通全流程）

用于 PoC 阶段快速验证框架和渲染效果，
返回预设的批改结果数据，不调用任何外部API。
"""

from grader_base import (
    GradingStrategy, GradingInput, GradingResult,
    SentenceAnalysis, ErrorItem, BoundingBox,
    ErrorType, Confidence, GradingStatus,
)


class MockGrader(GradingStrategy):
    """
    模拟批改器 — 返回预设的《小石潭记》批改结果。
    用于无API环境下验证框架和渲染效果。
    """

    @property
    def name(self) -> str:
        return "MockGrader (模拟数据)"

    @property
    def supports_bbox(self) -> bool:
        return True  # 模拟也返回坐标

    def grade(self, grading_input: GradingInput) -> GradingResult:
        """返回预设的模拟批改结果"""
        import time
        start = time.time()

        # 模拟延迟（假装在处理）
        time.sleep(0.5)

        result = GradingResult(
            recognized_text="从小丘向西走一百二十步，隔着竹林，听到水声，好像玉佩玉环碰撞的声音，心里很高兴。于是攻打竹子取得道路，往下看见一个小潭，潭水格外清凉。潭以整块石头为底，靠近岸边石底翻卷过来露出水面，成为坻、屿、嵁、岩各种形态。青葱的树木翠绿的藤蔓，蒙盖缠绕摇曳牵连，参差不齐随风飘拂。",
            total_score=82,
            overall_comment="整体翻译基本通顺，对文意把握较好。主要问题在个别实词的古今异义辨析不准确，如'伐''以为'等关键词需加强记忆。",
            confidence=Confidence.HIGH,
            status=GradingStatus.SUCCESS,
            grader_name=self.name,
            processing_time_ms=int((time.time() - start) * 1000),
        )

        # 逐句分析 — 模拟3个句子的批改
        result.sentence_analyses = [
            # 第1句：正确
            SentenceAnalysis(
                original_classical="从小丘西行百二十步，隔篁竹，闻水声，如鸣佩环，心乐之。",
                student_translation="从小丘向西走一百二十步，隔着竹林，听到水声，好像玉佩玉环碰撞的声音，心里很高兴。",
                standard_translation="从小丘向西走一百二十步，隔着竹林，听到了水声，好像玉佩玉环碰撞发出的声音，心里很高兴。",
                errors=[],
                sentence_score=20,
                is_excellent=True,
            ),
            # 第2句：有错误
            SentenceAnalysis(
                original_classical="伐竹取道，下见小潭，水尤清冽。",
                student_translation="于是攻打竹子取得道路，往下看见一个小潭，潭水格外清凉。",
                standard_translation="于是砍伐竹林开辟道路，往下看见一个小水潭，潭水格外清凉。",
                errors=[
                    ErrorItem(
                        error_type=ErrorType.CONTENT_ERROR,
                        original_text="攻打",
                        correct_text="砍伐",
                        reason="'伐'在本文中意为'砍伐'，非军事意义上的'攻打'。古今异义，需重点记忆。",
                        deduction_points=4,
                        bbox=BoundingBox(180, 245, 298, 275),  # 模拟坐标
                    ),
                    ErrorItem(
                        error_type=ErrorType.CONTENT_ERROR,
                        original_text="取得道路",
                        correct_text="开辟道路",
                        reason="'取道'应译为'开辟道路'，'取得'是现代汉语用法，不符合古文语境。",
                        deduction_points=2,
                        bbox=BoundingBox(300, 245, 420, 275),
                    ),
                ],
                sentence_score=14,
            ),
            # 第3句：有错误
            SentenceAnalysis(
                original_classical="全石以为底，近岸卷石底以出，为坻，为屿，为嵁，岩。",
                student_translation="潭以整块石头为底，靠近岸边石底翻卷过来露出水面，成为坻、屿、嵁、岩各种形态。",
                standard_translation="潭以整块石头为底，靠近岸边石底翻卷过来露出水面，成为坻、屿、嵁、岩等各种形态。",
                errors=[
                    ErrorItem(
                        error_type=ErrorType.OMISSION,
                        original_text="为坻，为屿，为嵁，岩",
                        correct_text="为坻，为屿，为嵁，为岩",
                        reason="原文'为坻，为屿，为嵁，岩'中'岩'前省略了'为'字，学生译文未补出，导致句式不完整。",
                        deduction_points=2,
                        bbox=BoundingBox(350, 320, 480, 350),
                    ),
                ],
                sentence_score=18,
            ),
            # 第4句：正确
            SentenceAnalysis(
                original_classical="青树翠蔓，蒙络摇缀，参差披拂。",
                student_translation="青葱的树木翠绿的藤蔓，蒙盖缠绕摇曳牵连，参差不齐随风飘拂。",
                standard_translation="青葱的树木翠绿的藤蔓，蒙盖缠绕摇曳牵连，参差不齐随风飘拂。",
                errors=[],
                sentence_score=20,
                is_excellent=True,
            ),
            # 第5句：有错误
            SentenceAnalysis(
                original_classical="潭中鱼可百许头，皆若空游无所依。",
                student_translation="潭中鱼大约有一百多条，都好像在空中游动没有什么依托。",
                standard_translation="潭中鱼大约有一百来条，都好像在空中游动没有什么依托。",
                errors=[
                    ErrorItem(
                        error_type=ErrorType.CONTENT_ERROR,
                        original_text="一百多条",
                        correct_text="一百来条",
                        reason="'可百许头'中'可'表约数'大约'，'许'表'左右/来'，译为'一百多条'不够准确，应为'一百来条'。",
                        deduction_points=2,
                        bbox=BoundingBox(280, 395, 380, 425),
                    ),
                ],
                sentence_score=18,
            ),
        ]

        return result
