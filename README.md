# AI 批改功能 PoC 框架

> **最小功能闭环**：上传图片 → 选择批改策略 → 查看批改完成图 + JSON报告

## 项目结构

```
poc_grader/
├── grader_base.py              # 抽象基类（所有策略的统一接口）
├── main.py                     # CLI 入口（命令行一键批改）
├── web_server.py               # Web 服务（浏览器上传查看）
│
├── graders/
│   ├── mock_grader.py          # 模拟批改器（无需API，验证渲染）
│   └── qwen_vl_max_grader.py  # Qwen-VL-Max 批改器（真实AI）
│
├── renderers/
│   └── grading_renderer.py    # 仿截图样式渲染器（左图右评）
│
├── utils/
│   └── generate_sample.py      # 生成模拟学生作业图片
│
├── output/                     # 输出目录
│   ├── sample_homework.jpg     # 模拟作业图片（测试用）
│   └── graded_result.jpg      # 批改完成图（示例）
│
└── tests/                      # 测试目录（待补充）
```

## 快速开始

### 方式1：命令行（CLI）

```bash
# 1. 进入项目目录
cd /workspace/poc_grader

# 2. Mock 模式（无需API，验证渲染效果）
python3.11 main.py \
  --image output/sample_homework.jpg \
  --grader mock \
  --output output/graded_result.jpg

# 3. Qwen-VL-Max 模式（需要 API Key）
export DASHSCOPE_API_KEY="sk-xxx"
python3.11 main.py \
  --image output/sample_homework.jpg \
  --grader qwen \
  --output output/graded_result.jpg
```

### 方式2：Web 服务（浏览器）

```bash
# 启动服务
python3.11 web_server.py

# 访问 http://localhost:8080
# 上传图片 → 自动批改 → 查看结果
```

## 核心设计：策略模式（可插拔切换）

```python
from main import get_grader

# 一行切换底层方案
grader = get_grader("mock")   # 模拟数据
grader = get_grader("qwen")   # Qwen-VL-Max
# grader = get_grader("gemini")  # 未来扩展
# grader = get_grader("baidu")   # 未来扩展

# 统一接口，无需关心底层实现
result = grader.grade(grading_input)
```

### 统一接口定义

所有批改策略必须实现 `GradingStrategy` 抽象基类：

| 方法 | 说明 |
|------|------|
| `name` | 策略名称标识 |
| `supports_bbox` | 是否支持坐标输出（Grounding） |
| `grade(input)` | 执行批改，返回 `GradingResult` |
| `validate()` | 验证策略可用性（API Key/网络） |

### 统一数据结构

```python
GradingResult:
  - recognized_text: str          # 识别到的学生文字
  - sentence_analyses: List[SentenceAnalysis]  # 逐句分析
  - total_score: int (0-100)      # 总分
  - overall_comment: str           # 总评
  - confidence: Confidence         # 高/中/低
  - status: GradingStatus          # 成功/异常状态
  - processing_time_ms: int        # 耗时
  - grader_name: str               # 使用的引擎
```

## 渲染效果

仿截图样式：
- **左侧（60%）**：原图 + 红色圆圈标注错误位置 + 蓝色序号标签
- **右侧（40%）**：详细点评列表（序号对应）+ 错误类型 + 判定理由 + 扣分
- **底部**：大号红色分数 + 总评 + 置信度 + 耗时

## 扩展新策略

要接入新的批改方案（如 Gemini、百度API），只需：

1. 在 `graders/` 下新建文件（如 `gemini_grader.py`）
2. 继承 `GradingStrategy` 抽象基类
3. 实现 `grade()` 方法，返回 `GradingResult`
4. 在 `main.py` 的 `get_grader()` 中注册

```python
# graders/gemini_grader.py
from grader_base import GradingStrategy, GradingInput, GradingResult

class GeminiGrader(GradingStrategy):
    @property
    def name(self): return "Gemini 2.0 Flash"
    
    @property
    def supports_bbox(self): return False  # Gemini 无 Grounding
    
    def grade(self, inp: GradingInput) -> GradingResult:
        # 调用 Gemini API
        # 解析响应 → 构建 GradingResult
        return result
```

## 当前状态

| 组件 | 状态 | 说明 |
|------|------|------|
| 抽象基类 | ✅ 完成 | 统一接口定义 |
| Mock 批改器 | ✅ 完成 | 模拟数据，无需API |
| Qwen-VL-Max 批改器 | ✅ 完成 | 需配置 DashScope API Key |
| 渲染器 | ✅ 完成 | 仿截图左图右评样式 |
| CLI 入口 | ✅ 完成 | 命令行一键运行 |
| Web 服务 | ✅ 完成 | 浏览器上传查看 |
| 测试图片生成 | ✅ 完成 | 模拟学生作业 |
| Gemini 批改器 | ⏳ 待扩展 | 框架已就绪 |
| 百度 API 批改器 | ⏳ 待扩展 | 框架已就绪 |
| 真实学生样本测试 | ⏳ 待提供 | 需要真实作业照片 |

## 待确认事项

- [ ] **DashScope API Key**：是否已有阿里云账号？
- [ ] **真实学生作业照片**：能否提供 10-20 张《小石潭记》翻译作业？
- [ ] **国庆老师批改标准**：用于精细化 Prompt 规则
- [ ] **Demo 形式**：周三展示用 CLI 还是 Web 页面？

## 技术栈

- Python 3.11
- Pillow（图像处理/渲染）
- Flask（Web 服务）
- OpenAI SDK（兼容 DashScope API）
- 策略模式（可插拔架构）
