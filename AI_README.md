# AI 协作快速上手指南

> 本文档专为其他 AI 工具（CodeBuddy、Claude、Cursor 等）设计，帮助快速理解项目全貌并继续开发。

---

## 一、这是什么项目？

**《小石潭记》AI 文言文翻译批改系统** — 一个完整的 Web 应用，用于：
- 学生上传手写文言文翻译作业照片
- AI 自动识别手写文字并逐句批改
- Canvas 标注错误位置（波浪线/直线/星星）
- 生成详细的批改报告（分数、维度分析、优缺点）

## 二、核心架构（关键！）

```
三层融合架构：
  百度OCR（手写识别 + 行坐标）
    → 规则引擎（句子匹配 + 初判）
      → LLM（Qwen 或豆包）终判
        → 坐标融合 → Canvas 标注
```

**最关键的文件（按重要性）：**

| 优先级 | 文件 | 作用 |
|--------|------|------|
| ⭐⭐⭐ | `src/graders/fusion_grader.py` | 核心融合批改器，5阶段 pipeline |
| ⭐⭐⭐ | `src/web_server.py` | Flask 服务 + 完整 HTML 模板 |
| ⭐⭐⭐ | `src/static/js/app.js` | 前端主逻辑 |
| ⭐⭐ | `src/graders/qwen_vl_max_grader.py` | 阿里 Qwen 批改器 |
| ⭐⭐ | `src/graders/volcano_grader.py` | 火山引擎豆包批改器 |
| ⭐⭐ | `src/grader_base.py` | 基础类型定义 |
| ⭐ | `src/main.py` | 批改策略工厂 |
| ⭐ | `src/static/js/core/CanvasManager.js` | Canvas 标注渲染 |

## 三、如何快速运行？

```bash
cd src
export DASHSCOPE_API_KEY="sk-ws-H.EMDIIYR.jtU9.MEQCIDg63k7FDifjcSOhZIrLlfmhEyb7or87x8Ka3ljuyrKFAiA9kSj93j6TJaUlazt1R_IS1QC-DWan69IoLEyeIbaZhw"
export BAIDU_API_KEY="6QzUZkERoW31P0kZlpoA8Seh"
export BAIDU_SECRET_KEY="bmCwZukpPIUxAvssGdS12m9ITj5UhWod"
export VOLCANO_API_KEY="ark-ddbae8e5-c1ad-4200-8b1d-b8483adca0c6-9eda7"
python3 web_server.py
# 访问 http://localhost:8080
```

依赖：`flask`, `openai`, `pillow`, `jieba`

## 四、如何运行端到端测试？

```python
import os
os.environ['DASHSCOPE_API_KEY'] = "sk-ws-H.EMDIIYR..."
os.environ['BAIDU_API_KEY'] = "6QzUZkERoW31P0kZlpoA8Seh"
os.environ['BAIDU_SECRET_KEY'] = "bmCwZukpPIUxAvssGdS12m9ITj5UhWod"
os.environ['VOLCANO_API_KEY'] = "ark-ddbae8e5-c1ad-4200-8b1d-b8483adca0c6-9eda7"

from graders.fusion_grader import FusionGrader
from grader_base import GradingInput

# 使用 Qwen 后端
grader = FusionGrader(
    llm_provider="qwen",  # 或 "volcano"
    dashscope_api_key=os.environ['DASHSCOPE_API_KEY'],
    baidu_api_key=os.environ['BAIDU_API_KEY'],
    baidu_secret_key=os.environ['BAIDU_SECRET_KEY'],
)

gi = GradingInput(
    image_path="../test_data/20260706-224322.jpg",
    textbook_name="小石潭记",
    textbook_author="柳宗元",
)

for event in grader.grade_stream(gi):
    if event['type'] == 'stage':
        print(f"[{event['stage']}] {event['message']}")
    elif event['type'] == 'result':
        data = event['data']
        print(f"Score: {data['total_score']}, Errors: {data['total_errors']}")
```

## 五、A/B 对比测试结果

| 指标 | 阿里通义千问 | 火山引擎豆包 |
|------|-------------|-------------|
| 总分 | 94 | 78 |
| 错误数 | 12 | 13 |
| 标注数 | 10 | 21 |
| 精彩句 | 3 | 4 |
| 用时 | 49.6s | 52.1s |

## 六、已知待改进项

1. 豆包评分偏宽松 → 需调整 system prompt
2. 批量批改进度显示不够清晰
3. 缺少用户登录和作业历史
4. 标注编辑器需支持拖拽调整
5. 需支持更多文言文篇目

## 七、目录结构

```
ai-grader-package/
├── AI_README.md              # ← 你正在读的文件
├── PROJECT_OVERVIEW.md        # 完整项目文档
├── config/
│   └── supervisord.conf       # 部署配置
├── src/                       # 完整源代码
│   ├── web_server.py
│   ├── main.py
│   ├── grader_base.py
│   ├── graders/
│   ├── static/
│   ├── utils/
│   └── renderers/
├── test_data/                 # 测试样本
│   ├── 20260706-224322.jpg    # 真实学生作文
│   └── dbj15162399465-未点评习作-第1张.jpg
└── results/                   # 批改结果样例
    ├── graded_*.jpg
    └── graded_*_report.json
```
