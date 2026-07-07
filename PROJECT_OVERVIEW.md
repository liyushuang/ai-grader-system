# 《小石潭记》AI 文言文翻译批改系统 — 项目全貌

## 项目概述

基于多模型融合的 AI 文言文翻译批改系统，采用 **百度OCR + 规则引擎 + 多模态LLM** 三层融合架构，支持阿里通义千问和火山引擎豆包双 LLM 后端，对《小石潭记》学生手写翻译作业进行逐句批改、打分、标注和生成批改报告。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    Web 前端 (Flask + Fabric.js)           │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐  │
│  │ 图片上传  │  │ Canvas标注│  │ 批改报告面板           │  │
│  │ (批量)    │  │ (波浪线/  │  │ (分数/维度/优缺点)     │  │
│  │           │  │  直线/星星)│  │                       │  │
│  └──────────┘  └──────────┘  └───────────────────────┘  │
├─────────────────────────────────────────────────────────┤
│                    融合批改器 (FusionGrader)              │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐  │
│  │ Phase 1  │→│ Phase 2  │→│ Phase 3+4              │  │
│  │ 百度OCR  │  │ 规则引擎  │  │ LLM 终判 (可切换)      │  │
│  │ 手写识别  │  │ 初判+匹配 │  │ ┌───────────────────┐ │  │
│  │ 28行坐标 │  │ 11句/3错 │  │ │ Qwen-Max (阿里)    │ │  │
│  └──────────┘  └──────────┘  │ │ 或                 │ │  │
│                               │ │ 豆包Vision (火山)  │ │  │
│                               │ └───────────────────┘ │  │
│                               └───────────────────────┘  │
│  Phase 5: 坐标融合 → 精确标注位置                          │
├─────────────────────────────────────────────────────────┤
│                    基础设施                                │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐  │
│  │ Flask    │  │ SSE 流式  │  │ supervisord 进程管理   │  │
│  │ Web 服务  │  │ 实时推送  │  │ 自动重启 + 环境变量    │  │
│  └──────────┘  └──────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## 文件结构

```
poc_grader/
├── web_server.py              # Flask Web 服务器 (含 HTML 模板)
├── main.py                    # 批改策略工厂 (get_grader)
├── grader_base.py             # 基础类型定义 (GradingResult, SentenceAnalysis 等)
├── start_server.sh            # 服务启动脚本
│
├── graders/                   # 批改策略实现
│   ├── fusion_grader.py       # ★ 核心：融合批改器 (OCR + 规则 + LLM)
│   ├── qwen_vl_max_grader.py  # 阿里通义千问 VL 批改器
│   ├── volcano_grader.py      # 火山引擎豆包批改器 (新增)
│   ├── baidu_ocr_grader.py    # 百度手写 OCR 批改器
│   ├── rule_engine.py         # 规则引擎 (语义等价判断)
│   └── mock_grader.py         # 模拟批改器 (离线测试)
│
├── static/                    # 前端资源
│   └── js/
│       ├── app.js             # ★ 主应用逻辑
│       ├── vendor/fabric.min.js
│       ├── core/
│       │   ├── CanvasManager.js   # Fabric.js Canvas 管理
│       │   ├── AnnotationStore.js # 标注数据存储
│       │   └── UndoManager.js     # 撤销/重做
│       ├── annotations/
│       │   ├── WavyLine.js        # 波浪线标注 (精彩句)
│       │   ├── StraightLine.js    # 直线标注 (错误句)
│       │   └── StarAnnotation.js  # 星星标注 (点睛句)
│       └── components/
│           ├── GradingReportPanel.js  # 批改报告面板
│           └── SidePanel.js           # 侧边栏
│
├── utils/                     # 工具函数
│   ├── annotation_utils.py    # 标注生成/坐标转换
│   └── generate_sample.py     # 样本数据生成
│
├── renderers/                 # 渲染器
│   └── grading_renderer.py    # 批改结果渲染
│
└── output/                    # 输出目录
    ├── uploads/               # 上传的作业图片
    ├── graded_*.jpg           # 标注后的图片
    └── graded_*_report.json   # 批改结果 JSON
```

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | Fabric.js 5.x | Canvas 标注渲染 |
| 前端 | Vanilla JS | 无框架，原生 JavaScript |
| 后端 | Flask 2.x | Python Web 服务 |
| 流式 | SSE (Server-Sent Events) | 实时推送批改进度 |
| OCR | 百度手写OCR API | 28行/297字符识别 |
| NLP | 自研规则引擎 | jieba 分词 + 语义等价 |
| LLM | Qwen-Max (阿里) | 主 LLM 后端 |
| LLM | 豆包Vision (火山) | 备选 LLM 后端 |
| 部署 | supervisord | 进程管理 + 自动重启 |

## API 配置

在 `start_server.sh` 或 supervisord 配置中设置以下环境变量：

```bash
# 阿里通义千问
DASHSCOPE_API_KEY=sk-ws-H.EMDIIYR.jtU9.MEQCIDg63k7FDifjcSOhZIrLlfmhEyb7or87x8Ka3ljuyrKFAiA9kSj93j6TJaUlazt1R_IS1QC-DWan69IoLEyeIbaZhw

# 百度手写OCR
BAIDU_API_KEY=6QzUZkERoW31P0kZlpoA8Seh
BAIDU_SECRET_KEY=bmCwZukpPIUxAvssGdS12m9ITj5UhWod

# 火山引擎豆包
VOLCANO_API_KEY=ark-ddbae8e5-c1ad-4200-8b1d-b8483adca0c6-9eda7
```

## 启动方式

```bash
cd /workspace/poc_grader
export DASHSCOPE_API_KEY="..."
export BAIDU_API_KEY="..."
export BAIDU_SECRET_KEY="..."
export VOLCANO_API_KEY="..."
python3 web_server.py
# 访问 http://localhost:8080
```

## 批改流程

1. 用户上传手写作业图片（支持批量）
2. 百度OCR 识别手写文字 + 获取每行坐标
3. 规则引擎逐句匹配标准译文，做初判
4. LLM（Qwen 或豆包）基于图片 + OCR结果 + 规则初判做终判
5. 融合 LLM 语义判断 + OCR 精确坐标 → 生成 Canvas 标注
6. 前端渲染波浪线（精彩句）、直线（错误句）、星星（点睛句）
7. 生成批改报告（分数、维度分析、优缺点、家长建议）

## 批改策略选择

前端提供 4 种批改策略：

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| 融合批改（推荐） | 百度OCR + 规则 + Qwen | 日常批改，最准确 |
| Qwen-VL-Max | 纯 Qwen 端到端 | 快速验证 |
| 百度手写OCR | 纯 OCR + 规则 | 离线/低成本 |
| 融合批改-火山引擎 | 百度OCR + 规则 + 豆包 | A/B 对比测试 |

## A/B 对比测试结果 (2026-07-07)

使用真实学生作文测试，同一图片，仅切换 LLM 后端：

| 指标 | 阿里通义千问 | 火山引擎豆包 |
|------|-------------|-------------|
| 总分 | 94 | 78 |
| 错误数 | 12 | 13 |
| 标注数 | 10 | 21 |
| 精彩句 | 3 | 4 |
| 点睛句 | 2 | 8 |
| 用时 | 49.6s | 52.1s |

**结论**: 
- 阿里通义千问评分更严格，更适合正式批改场景
- 火山引擎豆包亮点识别更积极，标注更密集
- 两者在 OCR 和规则引擎层结果完全一致（28行/297字符）
- 差异仅来自 LLM 终判的语义理解风格不同

## 关键优化历程

1. 默认选中「融合批改」模式
2. SSE 流式输出内嵌显示（固定高度180px，不跳动）
3. LLM 输出可读化（解析JSON展示句子分析，非原始JSON）
4. 标注渲染优化（轻量波浪线/直线，固定像素偏移确保不压文字）
5. 坐标映射重写（sentence_text 匹配 OCR 行，字符级精确定位）
6. 系统提示词按《小石潭记批改要求》全面优化
7. 维度分析报告（每个评分维度展示优势/薄弱点）
8. 接入火山引擎豆包，支持 A/B 对比

## 待改进项

- [ ] 豆包评分偏宽松，可考虑增加系统提示词约束
- [ ] 批量批改时各图片间进度显示不够清晰
- [ ] 缺少用户登录和作业历史管理
- [ ] 标注编辑器可增加拖拽调整位置
- [ ] 支持更多文言文篇目（岳阳楼记、醉翁亭记等）
- [ ] 移动端适配
