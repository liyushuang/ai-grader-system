# Qwen-VL-Max 方案详细设计文档

> **方案定位**：AI批改功能 PoC 阶段首选技术方案（Grounding 能力原生支持）
> **验证课文**：《小石潭记》文言文翻译批改
> **日期**：2026年7月7日
> **状态**：待评审

---

## 一、方案总览

### 1.1 核心架构思路

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Qwen-VL-Max 端到端批改架构                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  学生作业图片(JPG/PNG)                                              │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────┐                                                   │
│  │ ① 预处理层    │  图片压缩/格式校验/质量检测                       │
│  └──────┬───────┘                                                   │
│         │                                                           │
│         ▼                                                           │
│  ┌─────────────────────────────────────────────┐                   │
│  │ ② Qwen-VL-Max 调用层（核心）                │                   │
│  │                                             │                   │
│  │  输入：图片 + System Prompt(批改规则)        │                   │
│  │       + User Prompt(任务指令)               │                   │
│  │                                             │                   │
│  │  输出：结构化JSON                            │                   │
│  │   ├─ recognized_text: 识别出的学生作答文字   │                   │
│  │   ├─ corrections: 错误修正列表              │                   │
│  │   │   ├─ original_text: 原文                 │                   │
│  │   │   ├─ correct_text: 正确译文             │                   │
│  │   │   ├─ error_type: 错误类型               │                   │
│  │   │   ├─ reason: 判定理由                    │                   │
│  │   │   └─ bbox: [x1,y1,x2,y2] ← Grounding!  │                   │
│  │   ├─ score: 总分(百分制)                     │                   │
│  │   └─ comment: 总体评语                       │                   │
│  └──────────────┬──────────────────────────────┘                   │
│                 │                                                   │
│                 ▼                                                   │
│  ┌─────────────────────────────────────────────┐                   │
│  │ ③ 结果后处理层                               │                   │
│  │   ├─ JSON 校验与解析                         │                   │
│  │   ├─ 坐标系转换(归一化→像素)                  │                   │
│  │   └─ 异常结果重试/降级策略                    │                   │
│  └──────────────┬──────────────────────────────┘                   │
│                 │                                                   │
│                 ▼                                                   │
│  ┌─────────────────────────────────────────────┐                   │
│  │ ④ 渲染标注层                                │                   │
│  │   └─ 在原图上绘制：                         │                   │
│  │      · 红色波浪线 → 翻译错误位置(bbox)       │                   │
│  │      · 绿色勾 → 翻译正确位置                 │                   │
│  │      · 右侧/底部批注文字                     │                   │
│  │      · 角落显示总分+评语                      │                   │
│  └──────────────┬──────────────────────────────┘                   │
│                 │                                                   │
│                 ▼                                                   │
│        输出：带红笔标注的批改完成图 + 结构化JSON报告                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 与原方案（OCR分离）的关键区别

| 维度 | 原方案（插件Demo时期） | Qwen-VL-Max 方案 |
|------|----------------------|-----------------|
| **OCR步骤** | 独立开源 OCR 引擎 | **Qwen-VL 内置**（视觉理解一体） |
| **坐标获取** | OCR 引擎输出 bbox | **Qwen-VL Grounding 原生输出 bbox** |
| **知识库匹配** | 单独的课文知识库查询 | **融入 Prompt 上下文中** |
| **AI判断引擎** | GPT 文本模型 | **Qwen-VL 自身完成理解+判断** |
| **中间产物** | 4步独立调试 | **1次API调用完成** |
| **误差累积** | 高（OCR错→全错） | **低（端到端联合优化）** |

### 1.3 为什么选 Qwen-VL-Max 而非其他模型

```
选择Qwen-VL-Max的决定性原因：

1️⃣ Grounding（坐标输出）— 这是唯一"必须有"的能力
   其他模型(GPT-4o/Claude/Gemini)都无法输出bbox坐标
   没有坐标就无法在原图上画红笔标注

2️⃣ 中文文言文理解能力业界最佳
   DocVQA得分92.5% > GPT-4V的88.4%
   训练数据含大量中文古籍，对《小石潭记》类课文天然友好

3️⃣ 国内服务，无网络障碍
   阿里云DashScope直接调用
   数据不出境，合规无忧

4️⃣ PoC阶段成本可控
   按量付费，小规模验证成本远低于GPT-4o/Claude
```

---

## 二、各层级详细设计

### 2.1 层①：预处理层

#### 功能职责
- 接收原始学生作业图片
- 执行必要的格式/质量标准化
- 为 Qwen-VL-Max 准备合格输入

#### 详细规格

| 子功能 | 说明 | 技术实现 | PoC阶段 |
|--------|------|---------|---------|
| **格式校验** | 仅接受 JPG/PNG/WebP | 文件头魔数检查 | ✅ 必做 |
| **尺寸限制** | 最大 10MB，推荐 < 4MB | 拒绝超限文件或压缩 | ✅ 必做 |
| **分辨率适配** | 最优输入 1024~2048px 长边 | 超大图等比缩放 | ⚠️ 建议做 |
| **质量预检** | 检测是否过于模糊/过暗 | 可用简单方差检测 | ❌ PoC可跳过 |
| **EXIF方向校正** | 自动旋转正立 | 读取EXIF Orientation | ✅ 必做（手机拍照常见） |

#### 关键代码逻辑（伪代码）

```python
def preprocess_image(raw_image_bytes: bytes) -> ProcessedImage:
    """
    预处理流水线
    """
    # 1. 格式校验
    img = Image.open(io.BytesIO(raw_image_bytes))
    if img.format not in ('JPEG', 'PNG', 'WEBP'):
        raise UnsupportedFormatError(f"仅支持 JPG/PNG/WebP, 实际: {img.format}")

    # 2. EXIF方向校正
    img = apply_exif_orientation(img)

    # 3. 尺寸控制（长边最大2048px）
    max_long_side = 2048
    if max(img.size) > max_long_side:
        ratio = max_long_side / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # 4. 质量压缩（目标<4MB）
    output_buffer = io.BytesIO()
    img.save(output_buffer, format='JPEG', quality=85, optimize=True)

    return ProcessedImage(
        data=output_buffer.getvalue(),
        original_size=img.size,  # 记录原始尺寸用于坐标映射
        processed_size=img.size,
        format='JPEG'
    )
```

---

### 2.2 层②：Qwen-VL-Max 调用层（★ 核心）

这是整个方案的**最关键环节**。设计重点包括：
1. **System Prompt 设计** — 注入国庆老师的批改规则
2. **User Prompt 设计** — 明确任务指令和输出格式约束
3. **输出 JSON Schema 定义** — 强制结构化输出
4. **调用参数配置** — 兼顾质量和速度

#### 2.2.1 API 接入方式

**服务商**：阿里云 DashScope（灵积模型服务）
**模型名**：`qwen-vl-max`
**API 类型**：兼容 OpenAI 格式的 `/v1/chat/completions`
**认证方式**：API Key（Bearer Token）

```bash
# 环境变量
export DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxx"
BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

#### 2.2.2 System Prompt（批改规则注入）

> ⚠️ **重要提示**：以下为框架模板，实际使用时需要根据国庆老师的批改标准文档填充具体规则。

```text
你是一位资深中学语文教师，专门负责批改初中文言文翻译作业。

## 你的身份
- 你有20年语文教学经验，精通文言文语法和古今异义
- 你的批改标准严格遵循教研组统一制定的评分细则
- 你的评语简洁、准确、有建设性

## 当前批改课文：《小石潭记》（柳宗元）

### 课文原文参考
从小丘西行百二十步，隔篁竹，闻水声，如鸣佩环，心乐之。
伐竹取道，下见小潭，水尤清冽。全石以为底，近岸卷石底以出，
为坻，为屿，为嵁，岩。青树翠蔓，蒙络摇缀，参差披拂。

潭中鱼可百许头，皆若空游无所依，日光下澈，影布石上。
佁然不动，俶尔远逝，往来翕忽，似与游者相乐。

潭西南而望，斗折蛇行，明灭可见。其岸势犬牙差互，不可知其源。
坐潭上，四面竹树环合，寂寥无人，凄神寒骨，悄怆幽邃。
以其境过清，不可久居，乃记之而去。

同游者：吴武陵、龚古、余弟宗玄。隶而从者，崔氏二小生：曰恕己，曰奉壹。

### 标准译文参考（作为判分基准）
【此处根据国庆老师的标准文档填入官方标准译文】

---

## 批改规则（必须严格遵守）

### 评分规则
- 满分100分，按句子/关键词组逐条扣分制
- 每个实词（名词、动词、形容词）翻译错误扣3-5分
- 每个虚词（之、乎、者、也、而、其等）翻译错误扣2分
- 句式/语序错误每处扣3分
- 漏译一处扣2分
- 多译（添加原文没有的内容）扣1分
- 错别字每个扣1分

### 重点字词判定细则（按优先级排序）

#### 🔴 一级重点词（必须准确，错即严重扣分）
【此处从国庆老师文档中提取《小石潭记》的重点实词列表】
示例格式：
- "伐" → 必须包含"砍伐/砍"义项，译为"攻打/讨伐"判错
- "以为" → 古义"把...作为"，不能译为现代汉语"认为"
- "可" → 此处表约数"大约"，不是"可以"

#### 🟡 二级重点词（要求较准确，适度容错）
【二级重点虚词和常用词】

#### 🟢 三级一般词（允许意译，不苛刻扣分）
【连词、语气助词等】

### 翻译质量维度
1. **信（准确性）**：是否忠实原文，无遗漏无添加（权重50%）
2. **达（通顺性）**：译文是否流畅自然（权重30%）
3. **雅（文采性）**：用词是否恰当得体（权重20%）

---

## 输出格式要求（严格遵守JSON格式）

你必须严格按照下面的JSON格式输出，不要输出任何其他内容。
如果某个字段无法确定，填 null 而不要编造。
```

#### 2.2.3 User Prompt（任务指令）

```text
请批改以下学生提交的《小石潭记》文言文翻译作业图片。

## 任务要求
1. 仔细识别图片中的每一个汉字（包括手写体）
2. 将学生的译文与标准译文逐句对照
3. 根据上述批改规则找出所有错误
4. 对每个错误标注其在图片中的位置（用bounding box坐标）
5. 给出总分和总体评语

## 输出JSON格式

请输出纯JSON（不要加markdown代码块标记），格式如下：

{
  "recognized_text": "你在图片中识别到的完整学生作答文字",
  "sentence_analysis": [
    {
      "original_classical": "对应的原文文言文句子",
      "student_translation": "学生对这句的翻译",
      "standard_translation": "该句的标准译文",
      "errors": [
        {
          "error_type": "错误类型(实词错误/虚词错误/漏译/多译/错别字/语序错误)",
          "original_text": "学生写错的原文",
          "correct_text": "应该写的正确内容",
          "reason": "为什么这样判定（引用具体规则）",
          "deduction_points": 扣分数值(数字),
          "bbox": [x1, y1, x2, y2]
        }
      ],
      "sentence_score": 该句得分
    }
  ],
  "total_score": 总分(0-100数字),
  "overall_comment": "总体评语(2-3句话，肯定优点+指出主要问题)",
  "confidence": 置信度(高/中/低)
}
```

#### 2.2.4 调用参数配置

```python
# Python 调用示例（使用 openai 兼容SDK）
from openai import OpenAI

client = OpenAI(
    api_key="your-dashscope-api-key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
    model="qwen-vl-max",  # ★ 模型选择
    
    # System Prompt：批改规则（约2000-3000token）
    messages=[
        {
            "role": "system",
            "content": SYSTEM_PROMPT  # 见上文 2.2.2
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": USER_PROMPT},  # 见上文 2.2.3
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                        "detail": "high"  # ★ high detail 以获得更好的OCR精度
                    }
                }
            ]
        }
    ],
    
    # 参数调优
    temperature=0.1,        # ★ 低温度确保稳定输出（批改不需要创意）
    top_p=0.9,
    max_tokens=4096,         # ★ 足够输出完整JSON（含多个错误项）
    
    # 响应格式（可选，如果DashScope支持的话）
    # response_format={"type": "json_object"}  # 强制JSON输出
)

result_text = response.choices[0].message.content
```

#### 2.2.5 关键参数决策说明

| 参数 | 取值 | 理由 |
|------|------|------|
| `model` | `qwen-vl-max` | 选Max版而非Plus/Lite，PoC追求最高质量 |
| `temperature` | **0.1** | 批改是确定性任务，低温度保证同一张图多次调用结果一致 |
| `detail` | `"high"` | high detail模式发送更高分辨率图像给模型，OCR更准 |
| `max_tokens` | **4096** | 一份作业可能有10+处错误，每处error对象约200 token，预留充足空间 |

#### 2.2.6 Grounding 输出示例（预期）

Qwen-VL-Max 返回的 bbox 坐标含义：
- **坐标系**：相对于输入图像的像素坐标
- **格式**：`[x1, y1, x2, y2]` 左上角+右下角
- **单位**：像素（整数）

```json
{
  "recognized_text": "从小丘向西走一百二十步，隔着竹林，听到水声...",
  "sentence_analysis": [
    {
      "original_classical": "伐竹取道",
      "student_translation": "攻打竹子取得道路",
      "standard_translation": "砍伐竹林开辟道路",
      "errors": [
        {
          "error_type": "实词错误",
          "original_text": "攻打",
          "correct_text": "砍伐",
          "reason": "'伐'在本文中意为'砍伐'，非军事意义上的'攻打'",
          "deduction_points": 4,
          "bbox": [245, 312, 298, 348]  // ★ 圈住"攻打"两个字的区域
        }
      ],
      "sentence_score": 16
    }
  ],
  "total_score": 82,
  "overall_comment": "整体翻译基本通顺，对文意把握较好。主要问题在个别实词的古今异义辨析不准确，如'伐''以为'等关键词需加强记忆。",
  "confidence": "高"
}
```

---

### 2.3 层③：结果后处理层

#### 功能职责
- 解析并校验模型返回的 JSON
- 处理异常情况（JSON格式错误、字段缺失、坐标越界）
- 提供重试和降级机制

#### 处理流程

```python
@dataclass
class GradingResult:
    """批改结果的规范化数据结构"""
    recognized_text: str
    sentence_analyses: List[SentenceAnalysis]
    total_score: int
    overall_comment: str
    confidence: str
    raw_response: str           # 原始响应（用于调试）
    image_dimensions: tuple     # 图像尺寸 (W, H)


def process_qwen_vl_response(
    raw_response: str,
    image_size: Tuple[int, int],
    max_retries: int = 2
) -> GradingResult:
    """
    后处理流水线
    """
    # Step 1: 清理响应文本（去除可能的markdown包裹）
    cleaned = clean_markdown_wrapper(raw_response)
    
    # Step 2: JSON 解析
    for attempt in range(max_retries + 1):
        try:
            parsed = json.loads(cleaned)
            break
        except json.JSONDecodeError as e:
            if attempt < max_retries:
                # 尝试修复常见JSON问题（尾逗号、单引号等）
                cleaned = attempt_json_repair(cleaned)
            else:
                raise GradingResponseError(f"JSON解析失败(已重试{max_retries}次): {e}")
    
    # Step 3: Schema 校验
    validate_result_schema(parsed)  # 检查必要字段存在且类型正确
    
    # Step 4: 坐标校验与归一化
    img_w, img_h = image_size
    for sentence in parsed.get('sentence_analysis', []):
        for error in sentence.get('errors', []):
            if 'bbox' in error and error['bbox']:
                error['bbox'] = validate_and_normalize_bbox(
                    error['bbox'], img_w, img_h
                )
    
    # Step 5: 分数合理性校验
    total = parsed.get('total_score', 0)
    if not (0 <= total <= 100):
        logger.warning(f"异常总分: {total}, clamp to [0,100]")
        parsed['total_score'] = max(0, min(100, total))
    
    return GradingResult(
        recognized_text=parsed.get('recognized_text', ''),
        sentence_analyses=parse_sentence_analyses(parsed),
        total_score=parsed['total_score'],
        overall_comment=parsed.get('overall_comment', ''),
        confidence=parsed.get('confidence', '中'),
        raw_response=raw_response,
        image_dimensions=image_size
    )


def validate_and_normalize_bbox(
    bbox: list, 
    image_width: int, 
    image_height: int
) -> list:
    """
    坐标校验：
    - 检查范围 [0, W] x [0, H]
    - clamp越界值
    - 最小框面积限制（避免退化点/线）
    """
    x1, y1, x2, y2 = bbox
    
    # Clamp到图像范围内
    x1 = max(0, min(x1, image_width))
    y1 = max(0, min(y1, image_height))
    x2 = max(0, min(x2, image_width))
    y2 = max(0, min(y2, image_height))
    
    # 确保坐标顺序正确
    if x1 > x2: x1, x2 = x2, x1
    if y1 > y2: y1, y2 = y2, y1
    
    # 最小框面积 20x20 像素
    min_size = 20
    if (x2 - x1) < min_size:
        center_x = (x1 + x2) / 2
        x1 = int(center_x - min_size/2)
        x2 = int(center_x + min_size/2)
    if (y2 - y1) < min_size:
        center_y = (y1 + y2) / 2
        y1 = int(center_y - min_size/2)
        y2 = int(center_y + min_size/2)
    
    return [x1, y1, x2, y2]
```

#### 异常处理策略

| 异常类型 | 处理方式 | 是否通知用户 |
|----------|---------|-------------|
| JSON 解析失败 | 重试1-2次 → 仍失败则记录原始响应供人工审核 | ✅ 是 |
| 缺少 bbox 字段 | 标记为"无坐标"，仅保留文字描述，不影响其他错误展示 | ⚠️ 警告 |
| bbox 坐标越界 | 自动 clamp 到图像边界 | ❌ 静默 |
| 总分异常(<0 或 >100) | clamp 到 [0,100] 并记录日志 | ⚠️ 警告 |
| 返回置信度为"低" | 标记该结果需人工复核 | ✅ 是 |
| API 调用超时(>30s) | 重试1次 → 仍超时则返回错误，建议用户稍后重试 | ✅ 是 |

---

### 2.4 层④：渲染标注层

#### 功能职责
- 接收批改结果（含 bbox 坐标）
- 在原图上层叠加可视化标注
- 输出"批改完成的图片"

#### 标注规范定义

| 标注元素 | 样式 | 含义 | 触发条件 |
|----------|------|------|---------|
| **红色波浪线** | 红色(#FF3333), 粗细3px, 波浪状 | ❌ 错误位置 | error_type 任意错误 |
| **绿色双横线** | 绿色(#22C55E), 粗细2px | ✅ 翻译优美/亮点句 | 句子无错误且表达出色 |
| **黄色下划线** | 黄色(#EAB308), 粗细2px | ⚠️ 不确定但疑似错误 | confidence="低"时的标记 |
| **右侧边注** | 黑色文字, 14px宋体 | 错误说明 | 每个 error 项 |
| **底部评语区** | 半透明黑底白字 | 总分+评语 | 始终显示 |
| **角标分数** | 红色圆圈+白色数字, 48px | 大号醒目分数 | 始终显示 |

#### 渲染效果示意

```
┌──────────────────────────────────────┐
│  《小石潭记》翻译作业 - AI批改结果     │
│                                      │
│  从小丘西~~行~~走一百二十步...        │  ← 红色波浪线圈住"行"(漏字)
│   ┌──────────┐                        │
│   │应为:"西行"│                        │  ← 右侧边注
│   └──────────┘                        │
│                                      │
│  ~~攻打~~竹子取得道路...              │  ← 红色波浪线圈住"攻打"(实词错)
│   ┌──────────────────┐               │
│   │"伐"应译为"砍伐"   │               │
│   │扣4分 (实词错误)   │               │
│   └──────────────────┘               │
│                                      │
│  ═══ 水特别清澈 ═══                   │  ← 绿色双横线(翻译精彩)
│                                      │
│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│
│  得分: ❽❼  评语: 整体通顺，个别实词  │  ← 底部评语栏
│  古今异义辨析需加强，重点复习"伐"、   │
│  "以为"、"可"等字                   │
└──────────────────────────────────────┘
```

#### 渲染实现方案（Python + PIL）

```python
from PIL import Image, ImageDraw, ImageFont
import math

def render_grading_annotations(
    original_image_path: str,
    grading_result: GradingResult,
    output_path: str
) -> str:
    """
    在原图上渲染批改标注
    返回输出文件路径
    """
    # 加载原图
    img = Image.open(original_image_path).convert('RGBA')
    draw = ImageDraw.Draw(img)
    W, H = img.size
    
    # === 1. 绘制错误标注（红色波浪线）===
    red = (255, 51, 51)
    for sentence in grading_result.sentence_analyses:
        for error in sentence.errors:
            if error.bbox:
                x1, y1, x2, y2 = error.bbox
                draw_wavy_line(draw, x1, y2+4, x2, y2+4, 
                              color=red, amplitude=3, period=10)
                
                # 右侧边注
                annotation = f"❌ {error.correct_text} (扣{error.deduction_points}分)"
                draw_text_annotation(draw, x2 + 10, y1, annotation, 
                                    color=red, font_size=14)
    
    # === 2. 绘制亮点标注（绿色双横线）===
    green = (34, 197, 94)
    for sentence in grading_result.sentence_analyses:
        if sentence.error_count == 0 and sentence.is_excellent:
            if sentence.bbox:
                x1, y1, x2, y2 = sentence.bbox
                draw_double_line(draw, x1, y2+2, x2, y2+2, color=green)
    
    # === 3. 底部评语栏 ===
    comment_bar_height = 80
    overlay = Image.new('RGBA', (W, comment_bar_height), (0, 0, 0, 180))
    img.paste(overlay, (0, H - comment_bar_height), overlay)
    
    draw = ImageDraw.Draw(img)
    
    # 左侧：大号分数
    score_text = f"{grading_result.total_score}"
    try:
        score_font = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zen.ttc", 48)
        comment_font = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zen.ttc", 16)
    except:
        score_font = ImageFont.load_default()
        comment_font = ImageFont.load_default()
    
    # 分数（红色圆形背景）
    score_x, score_y = 40, H - comment_bar_height + 15
    draw.ellipse([score_x, score_y, score_x+55, score_y+55], fill=red)
    draw.text((score_x+12, score_y+8), score_text, fill=(255,255,255), font=score_font)
    
    # 评语文字
    comment_text = grading_result.overall_comment
    # 自动换行（每行约25个中文字符）
    wrapped = text_wrap(comment_text, max_chars_per_line=35)
    for i, line in enumerate(wrapped):
        draw.text((110, H - comment_bar_height + 18 + i*22), 
                  line, fill=(255,255,255), font=comment_font)
    
    # === 4. 保存 ===
    img_rgb = img.convert('RGB')
    img_rgb.save(output_path, 'JPEG', quality=95)
    
    return output_path


def draw_wavy_line(draw, x_start, y_start, x_end, y_end, 
                    color, amplitude=3, period=10):
    """
    绘制波浪线（用于标注错误位置）
    """
    points = []
    num_points = int(x_end - x_start)
    for i in range(num_points):
        x = x_start + i
        offset = amplitude * math.sin(2 * math.pi * i / period)
        points.append((x, y_start + offset))
    
    if len(points) >= 2:
        draw.line(points, fill=color, width=3)


def draw_double_line(draw, x1, y, x2, y, color, gap=3):
    """
    绘制双横线（用于标注亮点/优秀翻译）
    """
    draw.line([(x1, y), (x2, y)], fill=color, width=2)
    draw.line([(x1, y+gap), (x2, y+gap)], fill=color, width=2)


def text_wrap(text, max_chars_per_line=35):
    """
    中文字符自动换行
    """
    lines = []
    while len(text) > max_chars_per_line:
        lines.append(text[:max_chars_per_line])
        text = text[max_chars_per_line:]
    lines.append(text)
    return lines


def draw_text_annotation(draw, x, y, text, color, font_size=14):
    """
    绘制右侧边注文字（带半透明背景以提高可读性）
    """
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zen.ttc", font_size)
    except:
        font = ImageFont.load_default()
    
    # 计算文字尺寸
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    
    # 背景
    draw.rectangle([x-3, y-3, x+tw+5, y+th+3], fill=(255,255,255,200))
    # 文字
    draw.text((x, y), text, fill=color, font=font)
```

---

## 三、端到端数据流

### 3.1 请求生命周期

```
时间线（单张图批改）:

t=0s      用户上传图片
   ↓
t=0.1s    预处理完成（压缩+格式化）
   ↓
t=0.1s    发起 Qwen-VL-Max API 调用
   ↓  （网络传输 + 模型推理）
t=5~15s   ← 收到 API 响应（取决于图片复杂度和服务器负载）
   ↓
t=15.1s   JSON 解析 + 坐标校验完成
   ↓
t=15.2s   渲染标注到原图
   ↓
t=15.3s   返回批改完成图 + JSON报告给前端

总计延迟：约 5~20 秒/张（异步场景可接受）
```

### 3.2 数据流序列图

```
┌──────┐     ┌──────────┐     ┌───────────────┐     ┌──────────┐     ┌──────┐
│ APP/ │     │  后端服务  │     │ DashScope API  │     │ 渲染引擎  │     │ 存储  │
│ 前端  │     │ (Python)  │     │ (Qwen-VL-Max)  │     │ (PIL)    │     │      │
└──┬───┘     └────┬─────┘     └───────┬───────┘     └────┬─────┘     └──┬───┘
   │              │                   │                   │              │
   │  ①上传图片    │                   │                   │              │
   │ ────────────▶ │                   │                   │              │
   │              │                   │                   │              │
   │              │  ②预处理(压缩等)    │                   │              │
   │              │ ──────────────────────────────────────▶│              │
   │              │                   │                   │              │
   │              │  ③调用Qwen-VL-Max  │                   │              │
   │              │ ─────────────────▶ │                   │              │
   │              │                   │                   │              │
   │              │   ④返回结构化JSON  │                   │              │
   │              │ ◀───────────────── │                   │              │
   │              │                   │                   │              │
   │              │  ⑤渲染标注到原图    │                   │              │
   │              │ ──────────────────────────────────────▶│              │
   │              │                   │                   │              │
   │              │  ⑥保存批改完成图    │                   │              │
   │              │ ──────────────────────────────────────────────────────▶│
   │              │                   │                   │              │
   │  ⑦返回结果    │                   │                   │              │
   │ ◀─────────── │                   │                   │              │
   │  (批改图URL+JSON)                 │                   │              │
   │              │                   │                   │              │
```

---

## 四、Prompt 工程细节（★ 决成败的关键）

### 4.1 Prompt 结构设计原则

```
┌────────────────────────────────────────────────────────────┐
│                    Prompt 层级架构                          │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  L1 System Prompt（固定不变）                               │
│  ├── 身份设定："你是资深语文教师..."                         │
│  ├── 课文原文（《小石潭记》全文）                             │
│  ├── 标准译文（官方基准答案）                                 │
│  ├── 批改规则（扣分细则+重点字词表）← 从国庆老师文档提取      │
│  └── 输出格式约束（JSON Schema定义）                         │
│                                                            │
│  L2 User Prompt（每次请求相同模板）                          │
│  ├── 任务指令："请批改以下作业图片..."                       │
│  └── 图片数据（Base64）                                     │
│                                                            │
│  L3 动态变量（按课文切换时更新）                              │
│  └── 不同课文 → 替换 L1 中的"原文+标准译文+重点词表"        │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 4.2 批改规则提取流程（从国庆老师的文档到Prompt）

```
国庆老师批改标准文档(~100页/篇)
        │
        ▼
  ┌─────────────┐
  │ 人工提炼/结构化 │  ← 产品/教研协作完成
  └──────┬──────┘
         │
         ▼
  重点字词表（三级分类）
  ├── 一级重点（实词，错扣3-5分）：伐、以为、可、清冽、...
  ├── 二级重点（虚词/常用词，错扣2分）：之、其、而、者、...
  └── 三级一般（容错度高）：连词、助词等
  
  句式规则
  ├── 倒装句式辨识
  ├── 省略句补足
  └── 判断句格式

  评分权重配置
  ├── 信(准确性): 50%
  ├── 达(通顺性): 30%
  └── 雅(文采性): 20%
         │
         ▼
  注入到 System Prompt 的"批改规则"章节
```

### 4.3 Few-Shot 示例（提升输出质量的关键技巧）

在 User Prompt 中追加 1-2 个**已标注好的示例**，可以大幅提高 Qwen-VL-Max 输出的稳定性：

```text
## 示例参考（请按照此格式输出）

### 示例1：实词错误案例
【假设同时提供一张示例图片（可选，增加token消耗但效果更好）】
学生作答："全石以底"  （漏了"为"字）
期望输出：
{
  "errors": [{
    "error_type": "漏译",
    "original_text": "全石以底",
    "correct_text": "全石以为底",
    "reason": "'以为'是固定结构，意为'把...作为'，漏译'为'字改变原意",
    "deduction_points": 2,
    "bbox": [180, 245, 280, 275]
  }],
  "sentence_score": 18
}

### 示例2：满分案例
学生作答："水下有大约一百多条鱼"
期望输出：
{
  "errors": [],
  "sentence_score": 20,
  "is_excellent": true
}
```

> **PoC阶段建议**：先不加 few-shot 示例跑 baseline，再加 1 个示例对比效果提升幅度。

### 4.4 Prompt 优化迭代计划

| 版本 | 策略 | 目标 | 预期效果 |
|------|------|------|---------|
| **V1（MVP）** | 基础规则 + JSON格式约束 | 跑通流程 | 准确率 ~70% |
| **V2** | 加入 Few-shot 示例(1-2个) | 稳定输出格式 | 准确率 ~80% |
| **V3** | 细化重点字词表（一级/二级/三级） | 提升判断精准度 | 准确率 ~85% |
| **V4** | 加入思维链(CoT)："请先分析每句再打分" | 减少幻觉/乱判 | 准确率 ~88% |
| **V5（生产级）** | 全量规则 + 多示例 + 后处理规则引擎兜底 | 达到人工水平 | 准确率 >90% |

---

## 五、错误处理与边界情况

### 5.1 图片质量问题及应对

| 问题现象 | 可能原因 | 应对策略 |
|----------|---------|---------|
| 图片完全模糊无法辨认 | 对焦失败/运动模糊 | 返回"图片质量不佳请重拍"，confidence="低" |
| 图片颠倒/侧向 | 手机拍照 EXIF 未处理 | 预处理层自动校正 |
| 图片中有多页内容 | 学生拍了整本作业 | 提示"请逐页上传"，或裁切后分别处理 |
| 图片中有无关内容（桌面/手指遮挡） | 拍摄不规范 | 模型自行忽略无关区域（Qwen-VL有一定鲁棒性） |
| 手写字迹极其潦草 | 学生书写习惯差 | 标记 confidence="低"，建议人工复核 |
| 光照不均/阴影覆盖 | 拍摄环境差 | Qwen-VL对此容忍度较高；极端情况标记低置信度 |

### 5.2 模型输出异常及应对

| 异常表现 | 原因分析 | 处理方式 |
|----------|---------|---------|
| 返回非 JSON（夹杂文字解释） | 模型未遵循指令 | 后处理：尝试提取JSON部分；失败则重试 |
| JSON 字段缺失（缺少 bbox） | 模型"忘记"输坐标 | 缺失项用 null 填充，该错误仅文字展示无红圈 |
| bbox 坐标明显偏移 | Grounding 精度不足 | 后处理 clamp + 最小面积保护；PoC阶段记录偏差数据 |
| 重复标注同一错误 | 模型冗余输出 | 后处理去重（基于文本相似度 + bbox IoU） |
| 漏判明显错误 | 模型"眼花" | 无法自动恢复；记录为 false negative，后续优化Prompt |
| 给出极高分数但明显有错 | 模型"放水" | 设置最低阈值：如有bbox标注则分数应有对应扣分 |
| 编造原文中没有的内容 | 模型幻觉 | 与知识库原文交叉验证（未来版本） |

### 5.3 API 层异常

| 异常 | HTTP状态码 | 处理方式 |
|------|-----------|---------|
| API Key 无效 | 401 | 返回"服务配置错误"，通知管理员 |
| 余额不足 | 402 | 返回"配额用完"，提示升级套餐 |
| 请求频率超限 | 429 | 指数退避重试（1s→2s→4s→8s），最多3次 |
| 模型服务不可用 | 500/503 | 重试1次 → 仍失败则返回"服务繁忙请稍后重试" |
| 单次请求超时(>30s) | 客户端超时 | 取消请求，返回"处理超时" |
| 图片过大被拒 | 400 | 前端预处理压缩后重试 |

---

## 六、性能与成本估算

### 6.1 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| **单图端到端延迟** | < 20 秒 | 从上传到返回批改完成图（含API调用+渲染） |
| **API 调用耗时** | 5~15 秒 | Qwen-VL-Max 推理时间（受图片复杂度和排队影响） |
| **渲染耗时** | < 1 秒 | PIL 绘制标注（本地执行，很快） |
| **并发能力** | 10 并发请求 | PoC阶段足够；生产环境需队列削峰 |
| **可用性目标** | 99%（PoC不承诺SLA） | 依赖 DashScope 服务可用性 |

### 6.2 成本估算

**计费模式**：DashScope 按 token 计费（输入+输出分别计价）

**单次调用 token 消耗估算（一张作业图）：**

| 组成部分 | 估算 token 数 | 说明 |
|----------|--------------|------|
| System Prompt | ~2500 tokens | 身份+原文+规则+格式约束 |
| User Prompt 文字 | ~200 tokens | 任务指令 |
| 图片(Base64, high detail) | ~3000-8000 tokens | 取决于图片分辨率和内容密度 |
| **输入合计** | **~5700~10700 tokens** | | |
| 模型输出(JSON) | ~500-2000 tokens | 取决于错误数量 |
| **输出合计** | **~500-2000 tokens** | | |

**Qwen-VL-Max 参考价格**（以 DashScope 实际定价为准）：

```
假设价格：输入 ¥0.008/千tokens，输出 ¥0.008/千tokens
（仅为估算，具体以阿里云官网为准）

单次调用成本 ≈ (10000 input + 1000 output) × ¥0.008/1000
             ≈ ¥0.088 ≈ **不到1毛钱**
```

**规模化后成本预估：**

| 日均批改量 | 日成本 | 月成本(22工作日) |
|-----------|--------|----------------|
| 100 份（PoC/试点班级） | ~¥9 | ~¥198 |
| 1,000 份（年级推广） | ~¥88 | ~¥1,936 |
| 10,000 份（全校/多校） | ~¥880 | ~¥19,360 |

> 💡 **对比**：同等规模下 GPT-4o 月成本约 ¥45,000~90,000，Claude 约 ¥75,000~150,000

---

## 七、PoC 验证计划

### 7.1 验证目标

| 目标 | 度量方式 | 通过标准 |
|------|---------|---------|
| **OCR准确率** | 模型识别的文字 vs 人工核对 | 文字识别准确率 ≥ 90% |
| **Grounding精度** | bbox坐标是否精准圈住错误文字 | IoU ≥ 0.7 的比例 ≥ 70% |
| **批改一致性** | AI判分 vs 人工判分差距 | 分差 ≤ 10分的比例 ≥ 80% |
| **错误召回率** | AI找出的错误 vs 人工找出全部错误 | Recall ≥ 85% |
| **错误精确率** | AI判的错误中真正错误的比例 | Precision ≥ 85% |
| **端到端成功率** | 完整流程跑通无报错的比例 | ≥ 95% |
| **输出格式合规率** | 返回合法JSON且字段完整的比例 | ≥ 90% |

### 7.2 测试数据集准备

```
测试样本需求：《小石潭记》学生翻译作业照片

数量：15-20 张
分布：
├── 优秀作业（90分+）：3-4 张
├── 良好作业（75-89分）：4-5 张  
├── 及格作业（60-74分）：4-5 张
├── 不及格（<60分）：3-4 张
└── 特殊情况：1-2 张
    ├── 手写潦草
    ├── 有涂改痕迹
    └── 图片质量较差

来源：请提供历史学生作业照片（脱敏处理）
```

### 7.3 验证步骤

```
Day 1（周一）：
  ☐ 环境搭建：DashScope账号开通 + API Key获取
  ☐ 基础代码骨架：预处理 → API调用 → JSON解析 → 渲染
  ☐ 用1张简单图片跑通全流程（Hello World级别验证）

Day 2（周二）：
  ☐ Prompt V1编写：基础规则 + JSON格式约束
  ☐ 用5张图片初步测试，收集输出样例
  ☐ 快速分析：哪些地方判断对了？哪些错了？为什么？
  ☐ Prompt 迭代调整（针对性修补明显问题）

Day 3（周三·Demo日）：
  ☐ 用全部15-20张图片跑完整测试
  ☐ 统计各项指标（准确率/召回率/一致性等）
  ☐ 生成批改完成图样品（3-5张典型样例）
  ☐ 准备 Demo 展示材料：
    ├─ Before/After 对比图（原图 vs 批改后的图）
    ├─ 数据汇总表（指标达成情况）
    ├─ 失败案例分析（诚实展示局限）
    └─ 下一步优化方向
```

---

## 八、风险清单与缓解措施

| # | 风险 | 影响 | 概率 | 缓解措施 |
|---|------|------|------|---------|
| R1 | Qwen-VL-Max Grounding 精度不如预期 | bbox偏离导致红圈圈错位置 | 中 | Plan B：仅用文字描述错误位置，不画圈；Plan C：回退到百度API |
| R2 | DashScope 服务不稳定/延迟过高 | Demo 时卡顿丢脸 | 低 | 提前预热缓存；准备录屏作为备份 |
| R3 | 国庆老师的批改规则文档未及时到位 | Prompt规则不够精细 | 高 | 先用通用文言文翻译规则替代；文档到了再迭代 |
| R4 | 样本图片数量/质量不足 | 测试结论不具备代表性 | 中 | 用合成/模拟数据补充（AIGC生成手写体） |
| R5 | 成本超预期（模型比预期贵） | 影响后期推广决策 | 低 | PoC阶段用量极小，几乎可忽略；真实数据出来后再精算 |
| R6 | 输出 JSON 格式不稳定（模型有时不听话） | 后处理频繁报错 | 中 | 强化 Prompt 约束 + 后处理修复逻辑 + 重试机制 |
| R7 | 文言文专业术语判断不准 | 把对的判错（如特殊义项） | 中 | V3版本加入更详细的字词表；V4加入CoT思维链 |

---

## 九、后续演进路线（超出PoC范围）

### Phase 1：PoC（本周三）
- [x] 方案设计 ✅（本文档）
- [ ] 环境搭建 + 代码开发
- [ ] 《小石潭记》单课文验证
- [ ] Demo 演示

### Phase 2：MVP（+2周）
- [ ] 接入班主任工作流（APP内嵌或小程序）
- [ ] 支持更多课文（扩展 Prompt 模板库）
- [ ] 班主任人工复核界面（确认/AI修改）
- [ ] 批改结果推送家长（微信通知）
- [ ] 小规模试点（1-2个班，1-2周真实使用）

### Phase 3：正式版（+1-2月）
- [ ] 作文批改模块（第二优先级）
- [ ] 文学课笔记批改（第三优先级）
- [ ] 批改数据统计分析（班级共性错误 heatmap）
- [ ] 与教研系统联动（自动生成错题本/个性化练习推荐）
- [ ] 性能优化（并发/缓存/异步队列）

---

## 十、待确认事项

- [ ] **DashScope API Key**：是否已有？还是需要新申请？
- [ ] **国庆老师批改标准文档**：何时提供？（Prompt精细化依赖此文档）
- [ ] **学生作业样本图片**：能否提供 15-20 张《小石潭记》翻译作业照片？
- [ ] **Demo 形式确认**：周三 Demo 期望看到什么？
  - a) 终端命令行演示（开发者视角）
  - b) Web页面交互演示（产品视角）  
  - c) 纯结果图片+报告展示（最小可行）
- [ ] **开发执行人**：谁来做代码实现？（说话人2？新招？外包？）
- [ ] **渲染风格偏好**：红笔批注的具体样式是否有参考样例？

---

*文档版本：v1.0 | 最后更新：2026-07-7 | 作者：AI助手 | 状态：待评审*
