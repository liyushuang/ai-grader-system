"""
Qwen-VL-Max 批改策略实现

基于阿里云 DashScope 的 Qwen-VL-Max 多模态模型，
利用其原生 Grounding 能力输出错误位置的 bbox 坐标。
"""

import json
import time
import base64
import re
from typing import Optional, Tuple

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grader_base import (
    GradingStrategy, GradingInput, GradingResult,
    SentenceAnalysis, ErrorItem, BoundingBox,
    ErrorType, Confidence, GradingStatus,
    GradingException, APIException, ParseException,
)


class QwenVLMaxGrader(GradingStrategy):
    """
    使用 Qwen-VL-Max 进行端到端批改。
    核心优势：原生 Grounding 支持，可输出 bbox 坐标。
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen-vl-max",
        temperature: float = 0.1,
        max_tokens: int = 6144,
        max_retries: int = 1,
        timeout_seconds: int = 600,
    ):
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    # ── 接口属性 ──────────────────────────────────────

    @property
    def name(self) -> str:
        return f"Qwen-VL-Max (DashScope)"

    @property
    def supports_bbox(self) -> bool:
        return True  # ★ 核心差异化能力

    # ── 主入口 ────────────────────────────────────────

    def grade(self, grading_input: GradingInput) -> GradingResult:
        start_time = time.time()

        try:
            # Step 1: 加载图片并编码（同时获取压缩后尺寸，用于坐标映射）
            image_b64, processed_size = self._load_and_encode_image(grading_input)

            # Step 2: 构建 Prompt
            system_prompt = self._build_system_prompt(grading_input)
            user_content = self._build_user_content(grading_input, image_b64)

            # Step 3: 调用 API（带重试）
            raw_response, token_usage = self._call_api(
                system_prompt, user_content
            )

            # Step 4: 解析响应（传入压缩后尺寸用于坐标映射）
            result = self._parse_response(raw_response, grading_input, processed_size)

            # Step 5: 后处理校验
            result = self._post_process(result)

            result.grader_name = self.name
            result.token_usage = token_usage

        except GradingException:
            raise
        except Exception as e:
            raise APIException(
                f"Qwen-VL-Max 批改异常: {e}", self.name, cause=e
            )

        result.processing_time_ms = int((time.time() - start_time) * 1000)
        return result

    # ── 验证 ──────────────────────────────────────────

    def validate(self) -> Tuple[bool, str]:
        if not self.api_key:
            return False, "DashScope API Key 未配置"
        return True, ""

    # ── 图片处理 ──────────────────────────────────────

    def _load_and_encode_image(self, inp: GradingInput) -> Tuple[str, Tuple[int, int]]:
        """加载原图，不做任何压缩，直接 Base64 编码。返回 (base64, 原图尺寸)"""
        import io
        from PIL import Image

        if inp.image_data:
            raw = inp.image_data
        elif inp.image_path:
            with open(inp.image_path, "rb") as f:
                raw = f.read()
        else:
            raise GradingException("未提供图片数据(image_data或image_path)")

        img = Image.open(io.BytesIO(raw))
        orig_size = img.size
        print(f"   原图: {orig_size[0]}x{orig_size[1]}, {len(raw)//1024}KB (不压缩)")
        return base64.b64encode(raw).decode("utf-8"), orig_size

    # ── Prompt 构建 ───────────────────────────────────

    def _build_system_prompt(self, inp: GradingInput) -> str:
        """构建 System Prompt（注入精确标准译文参照）"""
        classical_text = inp.classical_text or self._default_classical_text()
        translation = inp.standard_translation or self._default_translation()
        sentence_pairs = self._default_sentence_pairs()
        highlights = self._default_highlight_sentences_text()

        return f"""你是一位资深中学语文教师，专门批改初中文言文翻译作业。

## 批改课文：《{inp.textbook_name}》（{inp.textbook_author}）

### 课文原文
{classical_text}

### 标准译文（完整）
{translation}

### 逐句精确参照（必须严格对照）
{sentence_pairs}

## 批改原则

1. **逐句对照**：将学生译文与上方逐句参照严格对比，按11句顺序输出
2. **语义等价宽容**：学生表达与标准译文语义相同但用词不同，视为正确不扣分：
   - "铺满石头为底" ≈ "以整块石头为底"
   - "心中很是快乐" ≈ "心里很高兴"
   - "没有任何东西靠着" ≈ "没有依托"
   - "听闻" ≈ "听到/听见"
3. **严格扣分**：实词错误(扣3-5分)、虚词错误(扣2-3分)、漏译(扣2分)、多译(扣1分)
4. **合理变体不扣分**：学生用自己的话表达相同含义不扣分

## 评分维度（各0-20分）

| 维度 | 评判标准 |
|------|---------|
| 完整度 | 实际翻译句子数/11 × 20 |
| 准确度 | 关键词翻译准确程度 |
| 重点词掌握 | 50+个重点实词虚词的掌握 |
| 句式处理 | 文言特殊句式处理 |
| 表达流畅度 | 现代汉语表达通顺程度 |
| 忠实原文 | 无随意增删 |

{highlights}

## 输出要求（严格纯JSON，不要markdown代码块）

{{
  "recognized_text": "学生完整译文",
  "sentence_analysis": [
    {{
      "original_classical": "原文句子（按11句顺序）",
      "student_translation": "学生翻译（该句未识别到写'未识别'）",
      "standard_translation": "标准译文",
      "errors": [
        {{
          "error_type": "实词错误|虚词错误|漏译|多译|错别字|语序错误|标点错误",
          "original_text": "学生错误内容",
          "correct_text": "正确内容",
          "reason": "判定理由（简明扼要）",
          "deduction_points": 扣分数值(1-5),
          "bbox": [x1,y1,x2,y2]
        }}
      ],
      "sentence_score": 该句得分(0-100),
      "is_excellent": true/false,
      "is_highlight": true/false,
      "highlight_comment": "点睛句赏析（仅is_highlight=true时填写）"
    }}
  ],
  "total_score": 总分(0-100),
  "overall_comment": "总评（2-3句，结合情感变化：闻水声→乐、观鱼→乐、坐潭上→凄怆、离去→记之）",
  "dimension_scores": {{
    "完整度": 0-20,
    "准确度": 0-20,
    "重点词掌握": 0-20,
    "句式处理": 0-20,
    "表达流畅度": 0-20,
    "忠实原文": 0-20
  }},
  "homework_completion": "作业完成情况（50字以内）",
  "strengths": ["优点1(具体)", "优点2(具体)"],
  "weaknesses": ["问题1(具体)", "问题2(具体)"],
  "suggestions": ["建议1(具体可执行)", "建议2(具体可执行)"],
  "highlight_sentences": [
    {{"classical": "原文点睛句", "translation": "学生译文", "comment": "赏析"}}
  ],
  "parent_feedback": "家长反馈话术（100字以内，正向引导+具体建议）",
  "system_tags": ["标签1", "标签2"],
  "confidence": "高|中|低"
}}

## 重要提醒

- bbox为像素坐标[左上x,左上y,右下x,右下y]，无法精确定位填null
- 总分=100-各句扣分总和，不低于0
- 6个维度各0-20分，独立评判，不可全部相同
- 优点至少2条，问题至少1条
- 点睛句至少标注5句
- 如学生只翻译了部分句子，完整度维度相应扣分
- 严格使用上方逐句参照中的标准译文，不要自行编造"""

    def _build_user_content(self, inp: GradingInput, image_b64: str) -> list:
        """构建 User Message（文字 + 图片）"""
        return [
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

    # ── API 调用 ──────────────────────────────────────

    def _call_api(self, system_prompt: str, user_content: list) -> Tuple[str, dict]:
        """调用 DashScope API，返回 (原始响应文本, token用量)"""
        import time as _time

        for attempt in range(self.max_retries + 1):
            try:
                # 延迟导入，避免未安装 openai 包时整个类加载失败
                from openai import OpenAI

                client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout_seconds,
                )

                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )

                raw = response.choices[0].message.content
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                }
                return raw, usage

            except Exception as e:
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    _time.sleep(wait)
                    continue
                raise APIException(
                    f"Qwen-VL-Max API 调用失败(已重试{self.max_retries}次): {e}",
                    self.name, cause=e
                )

    # ── 流式 API 调用 ──────────────────────────────────

    def _call_api_stream(self, system_prompt: str, user_content):
        """
        流式调用 DashScope API，逐 token 返回。
        
        Yields:
            dict: {"type": "llm_chunk", "text": "..."} 或 
                  {"type": "llm_done", "raw": "完整文本", "usage": {...}}
        """
        import time as _time
        from openai import OpenAI

        for attempt in range(self.max_retries + 1):
            try:
                client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout_seconds,
                )

                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                full_text = ""
                usage = {}
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        full_text += text
                        yield {"type": "llm_chunk", "text": text}
                    if hasattr(chunk, 'usage') and chunk.usage:
                        usage = {
                            "prompt_tokens": chunk.usage.prompt_tokens or 0,
                            "completion_tokens": chunk.usage.completion_tokens or 0,
                            "total_tokens": chunk.usage.total_tokens or 0,
                        }

                yield {"type": "llm_done", "raw": full_text, "usage": usage}
                return

            except Exception as e:
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    yield {"type": "llm_retry", "message": f"API调用失败，{wait}秒后重试...({e})"}
                    _time.sleep(wait)
                    continue
                yield {"type": "llm_error", "message": f"API调用失败(已重试{self.max_retries}次): {e}"}
                return

    # ── 响应解析 ──────────────────────────────────────

    def _parse_response(self, raw: str, inp: GradingInput, 
                         image_size: Tuple[int, int] = None) -> GradingResult:
        """解析模型返回的 JSON 为 GradingResult。image_size 为送API的图片尺寸，用于坐标映射。"""
        # 清理可能的 markdown 包裹
        cleaned = self._extract_json(raw)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ParseException(
                f"JSON 解析失败: {e}\n原始响应前200字符: {raw[:200]}",
                self.name
            )

        result = GradingResult(
            recognized_text=data.get("recognized_text", ""),
            total_score=data.get("total_score", 0),
            overall_comment=data.get("overall_comment", ""),
            confidence=Confidence(data.get("confidence", "中")),
            raw_response=raw,
        )

        # 解析逐句分析
        for sa_data in data.get("sentence_analysis", []):
            sa = SentenceAnalysis(
                original_classical=sa_data.get("original_classical", ""),
                student_translation=sa_data.get("student_translation", ""),
                standard_translation=sa_data.get("standard_translation", ""),
                sentence_score=sa_data.get("sentence_score", 0),
                is_excellent=sa_data.get("is_excellent", False),
                is_highlight=sa_data.get("is_highlight", False),
                highlight_comment=sa_data.get("highlight_comment", ""),
            )
            for err_data in sa_data.get("errors", []):
                if isinstance(err_data, str):
                    # qwen-plus 有时会输出字符串而非对象，跳过
                    continue
                error_item = ErrorItem(
                    error_type=self._parse_error_type(err_data.get("error_type", "")),
                    original_text=err_data.get("original_text", ""),
                    correct_text=err_data.get("correct_text", ""),
                    reason=err_data.get("reason", ""),
                    deduction_points=err_data.get("deduction_points", 0),
                )
                bbox_data = err_data.get("bbox")
                if bbox_data and len(bbox_data) == 4:
                    error_item.bbox = BoundingBox.from_list(bbox_data)
                sa.errors.append(error_item)
            result.sentence_analyses.append(sa)

        # 解析增强批改字段
        result.dimension_scores = data.get("dimension_scores", result.dimension_scores)
        result.dimension_analysis = data.get("dimension_analysis", {})
        result.homework_completion = data.get("homework_completion", "")
        result.strengths = data.get("strengths", [])
        result.weaknesses = data.get("weaknesses", [])
        result.suggestions = data.get("suggestions", [])
        result.highlight_sentences = data.get("highlight_sentences", [])
        result.parent_feedback = data.get("parent_feedback", "")
        result.system_tags = data.get("system_tags", [])

        return result

    def _post_process(self, result: GradingResult) -> GradingResult:
        """后处理：分数校验、置信度判定"""
        # 分数 clamp
        result.total_score = max(0, min(100, result.total_score))

        # 置信度判定
        if result.confidence == Confidence.LOW:
            result.status = GradingStatus.LOW_CONFIDENCE

        # 如果没有任何错误标注但分数很低 → 标记异常
        if result.total_score < 60 and result.total_errors == 0:
            result.status = GradingStatus.LOW_CONFIDENCE
            result.error_message = "分数低但未检测到具体错误，建议人工复核"

        return result

    # ── 辅助方法 ──────────────────────────────────────

    def _extract_json(self, text: str) -> str:
        """从文本中提取 JSON（处理模型偶尔包裹 markdown 的情况）"""
        # 尝试直接解析
        text = text.strip()
        if text.startswith("{"):
            return text

        # 去除 markdown 代码块
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 尝试找到 { 到 } 的范围
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return text[start:end+1]

        return text

    def _parse_error_type(self, raw: str) -> ErrorType:
        """将模型输出的错误类型字符串映射到枚举"""
        mapping = {
            "实词错误": ErrorType.CONTENT_ERROR,
            "虚词错误": ErrorType.FUNCTION_ERROR,
            "漏译": ErrorType.OMISSION,
            "多译": ErrorType.ADDITION,
            "错别字": ErrorType.TYPO,
            "语序错误": ErrorType.WORD_ORDER,
            "标点错误": ErrorType.PUNCTUATION,
        }
        return mapping.get(raw, ErrorType.CONTENT_ERROR)

    # ── 默认课文数据（后续从配置文件或数据库加载）─────

    @staticmethod
    def _default_classical_text() -> str:
        return """从小丘西行百二十步，隔篁竹，闻水声，如鸣佩环，心乐之。
伐竹取道，下见小潭，水尤清冽。全石以为底，近岸卷石底以出，
为坻，为屿，为嵁，岩。青树翠蔓，蒙络摇缀，参差披拂。

潭中鱼可百许头，皆若空游无所依，日光下澈，影布石上。
佁然不动，俶尔远逝，往来翕忽，似与游者相乐。

潭西南而望，斗折蛇行，明灭可见。其岸势犬牙差互，不可知其源。
坐潭上，四面竹树环合，寂寥无人，凄神寒骨，悄怆幽邃。
以其境过清，不可久居，乃记之而去。

同游者：吴武陵、龚古、余弟宗玄。隶而从者，崔氏二小生：曰恕己，曰奉壹。"""

    @staticmethod
    def _default_translation() -> str:
        return """从小丘向西走一百二十步，隔着竹林，听到了水声，好像玉佩玉环碰撞发出的声音，心里很高兴。
于是砍伐竹林开辟道路，往下看见一个小水潭，潭水格外清凉。
潭以整块石头为底，靠近岸边石底翻卷过来露出水面，
成为坻、屿、嵁、岩各种形态。青葱的树木翠绿的藤蔓，蒙盖缠绕摇曳牵连，参差不齐随风飘拂。

潭中鱼大约有一百来条，都好像在空中游动没有什么依托。
阳光直照到水底，鱼的影子映在石上。
鱼儿静止不动，忽然又向远处游去，来来往往轻快敏捷，好像和游人相互取乐。

向小石潭的西南方望去，看到溪水像北斗星那样曲折，像蛇那样蜿蜒前行，时隐时现。
那岸的形状像狗的牙齿那样相互交错，不能知道它的源头。
坐在小石潭上，四面竹子和树木环绕合抱，寂静寥落空无一人，
感到心神凄凉寒气透骨，幽静深远弥漫着忧伤的气息。
因为这里的环境太凄清，不可久居，于是记下这番景致就离开了。

一同游览的人：吴武陵、龚古，我的弟弟宗玄。跟随着同去的，还有姓崔的两个年轻人：一个叫恕己，一个叫奉壹。"""

    @staticmethod
    def _default_grading_rules() -> str:
        return """## 评分规则
- 满分100分，逐句扣分。一级实词错扣5分，二级虚词错扣3分，一般词错扣1分，漏译扣2分，多译扣1分，错别字扣1分，语序错扣2分

## 《小石潭记》重点字词速查表
逐句对照，格式：字词=正确翻译(扣分) | 常见错误

第1句(小丘西行→心乐之):
西=向西(3)|西方; 篁竹=竹林(5)|竹子; 如鸣佩环=好像玉佩玉环碰撞声(5)|像铃声; 乐=高兴(5)|喜欢

第2句(伐竹取道→水尤清冽):
伐=砍伐(5)|攻打; 取道=开辟道路(5)|取得道路; 下见=往下看见(2)|下面见; 尤=格外(3)|尤其; 清冽=清凉(5)|清澈

第3句(全石以为底→岩):
全石=整块石头(5)|全部石头; 以为=把…作为(5)|认为; 卷石底以出=石底翻卷露出水面(5)|卷起石头; 为坻/为岩=成为坻/岩(3/2)|漏译为字

第4句(青树翠蔓→披拂):
翠蔓=翠绿藤蔓(5)|绿蔓; 蒙络摇缀=蒙盖缠绕摇曳牵连(5)|垂下; 披拂=随风飘拂(5)|摇荡

第5句(潭中鱼→无所依):
可=大约(3)|可以; 许=来/左右(3)|多; 百许头=一百来条(5)|一百多条; 空游=在空中游动(5)|空游; 无所依=没有依托(3)|没有依靠

第6句(日光下澈→相乐):
下澈=直照水底(5)|往下清澈; 影布石上=影子映在石上(2)|影子在石上; 佁然=静止不动样子(5)|呆呆地; 俶尔=忽然(5)|突然; 翕忽=轻快敏捷(5)|迅速; 相乐=相互取乐(3)|一起玩

第7句(潭西南→可见):
斗折=像北斗星曲折(5)|弯折; 蛇行=像蛇蜿蜒前行(5)|蛇爬行; 明灭可见=时隐时现(5)|忽明忽暗

第8句(犬牙差互→其源):
犬牙差互=像狗牙交错(5)|犬牙交错; 源=源头(5)|来源

第9句(坐潭上→幽邃):
环合=环绕合抱(5)|围绕; 凄神寒骨=心神凄凉寒气透骨(5)|冷到骨头; 悄怆幽邃=幽静深远弥漫忧伤(5)|悄悄悲伤

第10句(以其境→而去):
以=因为(3)|用; 过清=太凄清(5)|太清; 居=停留(5)|居住; 乃=于是(3)|才; 记之而去=记下景致离开(2)|记下离开

第11句(同游者→奉壹):
同游者=一同游览的人(5)|同游的人; 余弟=我的弟弟(3)|弟弟; 隶而从者=跟随着同去(5)|奴隶跟随; 二小生=两个年轻人(5)|两个小孩

## 输出要求
逐句对照上表检查，输出JSON含error_type/bbox坐标"""

    @staticmethod
    def _default_highlight_sentences_text() -> str:
        return """## 必标点睛句（至少标注3句，在 sentence_analysis 中标记 is_highlight=true）
1. 心乐之 — 情感起点，"乐"字奠定全篇感情基调
2. 全石以为底/卷石底以出/为坻为屿为嵁为岩 — 石底奇观，铺排句式展现景物多样
3. 青树翠蔓/蒙络摇缀/参差披拂 — 景物描写典范，十二字写尽树木姿态
4. 空游无所依 — 千古名句，侧面写水清
5. 日光下澈/佁然不动/俶尔远逝/往来翕忽/相乐 — 动静结合写游鱼
6. 斗折蛇行/明灭可见/犬牙差互 — 比喻连用写溪流
7. 凄神寒骨/悄怆幽邃 — 情感由"乐"转"忧"的核心句
8. 以其境过清/不可久居/乃记之而去 — 收束全篇，点明离去原因"""

    @staticmethod
    def _default_sentence_pairs() -> str:
        """返回11句逐句对照（原文→标准译文），作为LLM精确参照"""
        return """第1句：从小丘西行百二十步，隔篁竹，闻水声，如鸣佩环，心乐之。
→ 从小丘向西走一百二十步，隔着竹林，听到了水声，好像玉佩玉环碰撞发出的声音，心里很高兴。

第2句：伐竹取道，下见小潭，水尤清冽。
→ 于是砍伐竹林开辟道路，往下看见一个小水潭，潭水格外清凉。

第3句：全石以为底，近岸卷石底以出，为坻，为屿，为嵁，为岩。
→ 潭以整块石头为底，靠近岸边石底翻卷过来露出水面，成为坻、屿、嵁、岩各种形态。

第4句：青树翠蔓，蒙络摇缀，参差披拂。
→ 青葱的树木翠绿的藤蔓，蒙盖缠绕摇曳牵连，参差不齐随风飘拂。

第5句：潭中鱼可百许头，皆若空游无所依。
→ 潭中鱼大约有一百来条，都好像在空中游动没有什么依托。

第6句：日光下澈，影布石上。佁然不动，俶尔远逝，往来翕忽，似与游者相乐。
→ 阳光直照到水底，鱼的影子映在石上。鱼儿静止不动，忽然又向远处游去，来来往往轻快敏捷，好像和游人相互取乐。

第7句：潭西南而望，斗折蛇行，明灭可见。
→ 向小石潭的西南方望去，看到溪水像北斗星那样曲折，像蛇那样蜿蜒前行，时隐时现。

第8句：其岸势犬牙差互，不可知其源。
→ 那岸的形状像狗的牙齿那样相互交错，不能知道它的源头。

第9句：坐潭上，四面竹树环合，寂寥无人，凄神寒骨，悄怆幽邃。
→ 坐在小石潭上，四面竹子和树木环绕合抱，寂静寥落空无一人，感到心神凄凉寒气透骨，幽静深远弥漫着忧伤的气息。

第10句：以其境过清，不可久居，乃记之而去。
→ 因为这里的环境太凄清，不可久留，于是记下这番景致就离开了。

第11句：同游者：吴武陵，龚古，余弟宗玄。隶而从者，崔氏二小生：曰恕己，曰奉壹。
→ 一同游览的人：吴武陵、龚古，我的弟弟宗玄。跟随着同去的，还有姓崔的两个年轻人：一个叫恕己，一个叫奉壹。"""

