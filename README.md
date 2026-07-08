# AI 批改 PoC - 标注编辑器

面向语文作业图片的批改与标注工具。当前重点验证《小石潭记》文言文翻译批改链路：上传学生作业图片后，系统完成 OCR、文本清洗、任务标准对齐、模型批改、OCR 坐标回填和批改报告生成。

## 当前能力

- 上传学生作业图片，默认进入上传页。
- 支持样式 Demo 页面：`/demo`。
- 支持两套文本模型入口：
  - `千问（推荐）`：百度 OCR + 规则初判 + Qwen 文本模型复核。
  - `方舟新模型`：复用同一套流程，只切换为方舟模型。
- 自动生成三类标注：
  - 点睛：绿色波浪线。
  - 纠错：红色直线。
  - 错字：红色圆圈。
- 旁批区采用老师手写式红字展示：
  - 左图标注序号与右侧旁批序号强对应。
  - 旁批展示问题类型和批改依据。
  - 错字直接在圆圈上方显示建议改成什么，不再只放到右侧列表。
- 批改报告包含：
  - 详细点评。
  - 教师总评：通用 / 鼓励 / 指导。
  - 订正建议。
  - 优秀表达。
  - 易错点。
  - 连贯全文润色。
- 报告字段由模型直接生成；模型失败或字段缺失时直接报错，不再用规则结果兜底冒充报告。

## 批改流程

```text
图片
  → 百度 OCR
  → 文本清洗
  → 动态任务标准对齐
  → 规则候选
  → 千问 / 方舟文本模型批改
  → OCR 坐标回填标注
  → 批改报告
```

核心约束：

- OCR 负责文字和字级坐标。
- 规则只生成候选问题，不再决定最终批改结果。
- 模型是最终文本批改者，可以确认、驳回或新增问题。
- 模型不能生成坐标，也不能改 OCR 字锚点。
- 画布标注只接收能和 OCR 字锚点精确对应的问题。
- 无法定位的问题进入报告，不自动画线。

## 项目结构

```text
.
├── grader_base.py                  # 批改数据结构和策略基类
├── main.py                         # CLI 入口
├── web_server.py                   # Web 服务
├── graders/
│   ├── fusion_grader.py            # 当前主流程：OCR + 规则 + 文本模型
│   ├── qwen_vl_max_grader.py       # OpenAI 兼容接口调用封装
│   └── mock_grader.py              # Mock 策略
├── static/js/                      # 标注编辑器前端
├── utils/annotation_utils.py       # 自动标注生成
├── test_data/                      # 测试图片
└── output/                         # 本地输出目录
```

## 环境变量

不要把真实 Key 写进代码或提交到 GitHub。推荐使用 `.env` 或命令行环境变量。

```bash
export BAIDU_API_KEY="你的百度OCR Key"
export BAIDU_SECRET_KEY="你的百度OCR Secret"

export DASHSCOPE_API_KEY="你的千问 Key"
export FUSION_QWEN_MODEL="qwen3.6-max-preview"

export ARK_API_KEY="你的方舟 Key"
export ARK_MODEL="ark-code-latest"
export ARK_BASE_URL="https://ark.cn-beijing.volces.com/api/plan/v3"
```

说明：

- `.env` 已在 `.gitignore` 中忽略。
- 方舟入口默认使用 `ark-code-latest`。
- 千问入口当前按 `qwen3.6-max-preview` 配置，无思考模式。

## 本地运行

```bash
cd /Users/admin/Documents/语文作业批改/ai-grader-system

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt  # 如果本地已有依赖可跳过

PORT=8084 python web_server.py
```

访问：

- 上传批改页：[http://127.0.0.1:8084](http://127.0.0.1:8084)
- 样式 Demo：[http://127.0.0.1:8084/demo](http://127.0.0.1:8084/demo)

## 命令行批改

```bash
python main.py \
  --image test_data/dbj2483646-未点评习作-第1张.jpg \
  --grader fusion \
  --output output/graded_result.jpg
```

方舟模型：

```bash
python main.py \
  --image test_data/dbj2483646-未点评习作-第1张.jpg \
  --grader ark_code \
  --output output/graded_result.jpg
```

## 测试数据

`test_data/` 中包含未点评图和已点评图：

- 未点评图：作为正式批改输入。
- 已点评图：只作为老师标注对照，不应作为批改输入，避免老师红字污染 OCR。

当前测试重点：

- 定位是否贴合 OCR 字词。
- 序号是否与右侧点评卡片一致。
- 点睛 / 纠错 / 圆圈错字是否符合老师标注习惯。
- 报告内容是否只围绕当前上传图片。
- 千问和方舟在同一流程下的效果差异。

## 当前批改策略

- 优先使用模型批改结果，规则只作为提示。
- 不按规则类型白名单过滤模型结果。
- 模型新增问题必须满足：
  - `anchor_ids` 来自 OCR。
  - `anchor_ids` 拼出的文字与 `evidence_text` 完全一致。
  - 证据文本足够短，适合画布定位。
- 自动标注最多 12 条，按教学优先级呈现。
- 旁批文案尽量使用老师口吻，避免暴露内部规则判断过程。
- 批改报告中的订正建议会带上问题类型和依据，便于复盘。
- 不做静默兜底：模型输出无效时直接失败，方便定位问题。

## 近期优化重点

- 千问和方舟共用同一套批改流程，只切换模型。
- AI 思考过程展示 6 个阶段：OCR识别、文本清洗、标准对齐、规则候选、模型批改、坐标回填。
- 思考过程会展示模型返回的问题候选、类型和依据，便于排查为什么某些问题没有进入画布。
- 批改页面弱化系统卡片感，旁批更接近老师红字批注。
- 标注区只保留点睛、纠错、圆圈错字三类，不再使用“精彩”标注。

## 常用检查

```bash
python -m py_compile web_server.py main.py graders/fusion_grader.py graders/qwen_vl_max_grader.py utils/annotation_utils.py

node --check static/js/app.js
node --check static/js/components/GradingReportPanel.js
node --check static/js/components/SidePanel.js
node --check static/js/core/CanvasManager.js
```
