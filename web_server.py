"""
简易 Web 服务 — 浏览器上传图片批改

启动：python web_server.py
访问：http://localhost:8080

功能：
- 上传学生作业图片
- 选择批改策略（Mock / Qwen-VL-Max）
- 查看批改完成图 + JSON报告
"""

import os
import sys
import json
import base64
from pathlib import Path
from flask import Flask, request, render_template_string, send_file, Response, stream_with_context

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "graders"))
sys.path.insert(0, str(PROJECT_ROOT / "renderers"))

from grader_base import GradingInput, Annotation, AnnotationType, AnnotationSource
from main import get_grader
from grading_renderer import GradingRenderer
from utils.annotation_utils import generate_annotations_from_result, annotations_to_dict_list, annotations_from_dict_list

# 兜底：如果环境变量未设置，使用硬编码的 API Key
if not os.environ.get("BAIDU_API_KEY"):
    os.environ["BAIDU_API_KEY"] = "6QzUZkERoW31P0kZlpoA8Seh"
if not os.environ.get("BAIDU_SECRET_KEY"):
    os.environ["BAIDU_SECRET_KEY"] = "bmCwZukpPIUxAvssGdS12m9ITj5UhWod"
if not os.environ.get("DASHSCOPE_API_KEY"):
    os.environ["DASHSCOPE_API_KEY"] = "sk-ws-H.EMDIIYR.jtU9.MEQCIDg63k7FDifjcSOhZIrLlfmhEyb7or87x8Ka3ljuyrKFAiA9kSj93j6TJaUlazt1R_IS1QC-DWan69IoLEyeIbaZhw"

app = Flask(__name__)

# HTML 模板 — 标注编辑器版本
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>AI 批改 PoC — 标注编辑器</title>
    <script src="/static/js/vendor/fabric.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
               background: #f0f2f5; height: 100vh; overflow: hidden; }
        
        /* ── 顶部导航栏 ── */
        .navbar { background: #1a1a2e; color: white; padding: 0 20px; height: 48px;
                  display: flex; align-items: center; justify-content: space-between; }
        .navbar h1 { font-size: 16px; font-weight: 600; }
        .navbar .nav-actions { display: flex; gap: 10px; align-items: center; }
        .nav-btn { background: rgba(255,255,255,0.1); color: white; border: none; 
                   padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
        .nav-btn:hover { background: rgba(255,255,255,0.2); }
        .nav-btn.primary { background: #4a90d9; }
        .nav-btn.primary:hover { background: #357abd; }
        .nav-btn.danger { background: #e74c3c; }
        
        /* ── 主布局 ── */
        .main-layout { display: flex; height: calc(100vh - 48px); }
        
        /* ── 工具栏 ── */
        .toolbar { width: 56px; background: white; border-right: 1px solid #e0e0e0;
                   display: flex; flex-direction: column; align-items: center; padding: 10px 0; gap: 4px; }
        .tool-btn { width: 40px; height: 40px; border: 2px solid transparent; border-radius: 8px;
                    background: #f8f9fa; cursor: pointer; display: flex; align-items: center; 
                    justify-content: center; font-size: 18px; transition: all 0.15s; position: relative; }
        .tool-btn:hover { background: #e8f0fe; border-color: #c4d7f2; }
        .tool-btn.active { background: #e8f0fe; border-color: #4a90d9; box-shadow: 0 0 0 2px rgba(74,144,217,0.2); }
        .tool-btn[data-tooltip]:hover::after { content: attr(data-tooltip); position: absolute;
            left: 50px; background: #333; color: white; padding: 4px 8px; border-radius: 4px;
            font-size: 11px; white-space: nowrap; z-index: 100; pointer-events: none; }
        .tool-separator { width: 30px; height: 1px; background: #e0e0e0; margin: 4px 0; }
        
        /* ── Canvas 区域 ── */
        .canvas-area { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
                       background: #e8ecf1; overflow: hidden; position: relative; }
        .canvas-container { box-shadow: 0 4px 20px rgba(0,0,0,0.15); }
        .canvas-upload-hint { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
            text-align: center; color: #999; pointer-events: none; }
        .canvas-upload-hint .hint-icon { font-size: 48px; margin-bottom: 10px; }
        .canvas-upload-hint p { font-size: 14px; }
        
        /* ── 侧边面板 ── */
        .side-panel { width: 320px; background: white; border-left: 1px solid #e0e0e0;
                      display: flex; flex-direction: column; overflow: hidden; }
        .panel-tabs { display: flex; border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }
        .panel-tab { flex: 1; padding: 10px 8px; text-align: center; font-size: 12px; font-weight: 500;
                     color: #999; cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s; }
        .panel-tab:hover { color: #666; background: #fafafa; }
        .panel-tab.active { color: #4a90d9; border-bottom-color: #4a90d9; font-weight: 600; }
        .panel-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .panel-header { padding: 10px 16px; border-bottom: 1px solid #f0f0f0; 
                        font-weight: 600; font-size: 13px; color: #333; 
                        display: flex; justify-content: space-between; align-items: center; }
        .panel-count { font-size: 12px; color: #999; font-weight: normal; }
        .annotation-list { flex: 1; overflow-y: auto; padding: 8px; }
        .ann-item { padding: 10px 12px; border-radius: 8px; margin-bottom: 6px; cursor: pointer;
                    border: 2px solid transparent; transition: all 0.15s; display: flex; gap: 10px; align-items: flex-start; }
        .ann-item:hover { background: #f8f9fa; }
        .ann-item.selected { border-color: #4a90d9; background: #f0f6ff; }
        .ann-item .ann-icon { width: 28px; height: 28px; border-radius: 6px; 
                               display: flex; align-items: center; justify-content: center; 
                               font-size: 14px; flex-shrink: 0; }
        .ann-item .ann-icon.wavy { background: #d1fae5; color: #059669; }
        .ann-item .ann-icon.line { background: #fee2e2; color: #dc2626; }
        .ann-item .ann-icon.star { background: #fef3c7; color: #d97706; }
        .ann-item .ann-content { flex: 1; min-width: 0; }
        .ann-item .ann-type-label { font-size: 11px; font-weight: 600; margin-bottom: 2px; }
        .ann-item .ann-type-label.wavy { color: #059669; }
        .ann-item .ann-type-label.line { color: #dc2626; }
        .ann-item .ann-type-label.star { color: #d97706; }
        .ann-item .ann-comment { font-size: 12px; color: #555; line-height: 1.4; 
                                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ann-item .ann-source { font-size: 10px; color: #aaa; margin-top: 2px; }
        .ann-item .ann-delete { opacity: 0; background: none; border: none; color: #999; 
                                cursor: pointer; font-size: 14px; padding: 2px 4px; transition: opacity 0.15s; }
        .ann-item:hover .ann-delete { opacity: 1; }
        .ann-item .ann-delete:hover { color: #e74c3c; }
        
        /* ── 编辑面板 ── */
        .edit-panel { padding: 16px; border-top: 1px solid #e0e0e0; display: none; }
        .edit-panel.active { display: block; }
        .edit-panel label { font-size: 12px; font-weight: 600; color: #666; display: block; margin-bottom: 4px; }
        .edit-panel select, .edit-panel textarea { width: 100%; border: 1px solid #ddd; border-radius: 6px; 
            padding: 8px 10px; font-size: 13px; margin-bottom: 10px; font-family: inherit; }
        .edit-panel textarea { height: 80px; resize: vertical; }
        .edit-panel .edit-actions { display: flex; gap: 8px; }
        .edit-btn { padding: 6px 14px; border-radius: 6px; border: none; cursor: pointer; font-size: 12px; }
        .edit-btn.save { background: #4a90d9; color: white; }
        .edit-btn.cancel { background: #f0f0f0; color: #666; }
        .edit-btn.delete { background: #fee2e2; color: #dc2626; }
        
        /* ── 批改报告面板 ── */
        .grading-report { flex: 1; overflow-y: auto; padding: 12px 16px; }
        .report-empty { padding: 30px 20px; text-align: center; color: #bbb; font-size: 13px; }
        .report-section { margin-bottom: 16px; }
        .report-score { text-align: center; padding: 12px 0; }
        .score-number { font-size: 48px; font-weight: 700; line-height: 1; }
        .score-label { font-size: 14px; color: #999; }
        .report-meta { display: flex; gap: 6px; flex-wrap: wrap; justify-content: center; margin-top: 4px; }
        .meta-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; }
        .meta-badge.error { background: #fee2e2; color: #dc2626; }
        .meta-badge.tag { background: #e0e7ff; color: #4a6cf7; }
        .report-label { font-size: 13px; font-weight: 600; color: #333; margin-bottom: 6px; }
        .report-text { font-size: 12px; color: #555; line-height: 1.7; }
        .report-text.feedback { background: #f0f9ff; padding: 10px; border-radius: 8px; border-left: 3px solid #4a90d9; }
        .report-list { list-style: none; padding: 0; }
        .report-list li { font-size: 12px; color: #555; padding: 4px 0 4px 16px; position: relative; line-height: 1.6; }
        .report-list li::before { position: absolute; left: 0; font-size: 11px; }
        .report-list.good li::before { content: '✓'; color: #52c41a; }
        .report-list.warn li::before { content: '!'; color: #faad14; font-weight: bold; }
        .report-list.tip li::before { content: '→'; color: #4a90d9; }
        .report-list.star li::before { content: '★'; color: #d97706; }
        .dim-item { margin-bottom: 10px; padding: 8px 10px; background: #fafbfc; border-radius: 8px; }
        .dim-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px; }
        .dim-name { font-size: 12px; color: #555; font-weight: 500; }
        .dim-score { font-size: 13px; font-weight: 700; }
        .dim-bar { height: 5px; background: #f0f0f0; border-radius: 3px; overflow: hidden; }
        .dim-fill { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
        .dim-analysis { margin-top: 4px; font-size: 11px; line-height: 1.5; }
        .dim-tag { display: inline-block; padding: 0 5px; border-radius: 3px; margin-right: 4px; font-weight: 600; font-size: 10px; }
        .dim-tag.good { background: #f0fdf4; color: #16a34a; }
        .dim-tag.warn { background: #fefce8; color: #ca8a04; }
        .dim-strength, .dim-weakness { padding: 2px 0; color: #666; }
        
        /* ── 迷你上下文菜单 ── */
        .context-menu { position: fixed; background: white; border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);
                        z-index: 200; display: none; overflow: hidden; min-width: 160px; }
        .context-menu .menu-item { padding: 10px 16px; cursor: pointer; font-size: 13px; color: #333;
                                   display: flex; align-items: center; gap: 8px; }
        .context-menu .menu-item:hover { background: #f0f6ff; }
        .context-menu .menu-item.danger { color: #dc2626; }
        .context-menu .menu-divider { height: 1px; background: #eee; }
        
        /* ── 上传区域（未批改时显示）── */
        .upload-overlay { display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(255,255,255,0.95); z-index: 10; align-items: center; justify-content: center; }
        .upload-overlay.show { display: flex; }
        .upload-card { text-align: center; padding: 40px; }
        .upload-card .upload-icon { font-size: 64px; margin-bottom: 16px; }
        .upload-card h2 { color: #333; margin-bottom: 8px; font-size: 20px; }
        .upload-card p { color: #999; margin-bottom: 24px; font-size: 14px; }
        .upload-card input[type="file"] { display: none; }
        .upload-card .upload-btn { background: #4a90d9; color: white; padding: 12px 32px;
            border-radius: 8px; border: none; font-size: 15px; cursor: pointer; }
        .upload-card .upload-btn:hover { background: #357abd; }
        .upload-card .grader-options { display: flex; gap: 12px; justify-content: center; margin: 16px 0; }
        .grader-option { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #666; }
        
        /* ── 状态栏 ── */
        .status-bar { position: absolute; bottom: 0; left: 56px; right: 320px; height: 28px;
                      background: rgba(255,255,255,0.9); border-top: 1px solid #e0e0e0;
                      display: flex; align-items: center; padding: 0 12px; font-size: 11px; color: #999; gap: 16px; }
        
        /* ── Loading ── */
        .loading-overlay { display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(255,255,255,0.8); z-index: 20; align-items: center; justify-content: center; }
        .loading-overlay.show { display: flex; }
        .spinner { width: 40px; height: 40px; border: 3px solid #f3f3f3; border-top: 3px solid #4a90d9;
                   border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
        /* ── Thinking Panel（内联展示，固定高度不跳动）── */
        .thinking-panel { display: none; margin: 8px 10px 0 10px;
            background: #fff; border: 1px solid #e8ecf1; border-radius: 10px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06); flex-direction: column; overflow: hidden;
            height: 180px; flex-shrink: 0; transition: all 0.3s ease; }
        .thinking-panel.show { display: flex; }
        .thinking-panel.collapsed .thinking-body { display: none; }
        .thinking-panel.collapsed { height: 38px; }
        .thinking-header { padding: 8px 14px; font-size: 13px; font-weight: 600; color: #333;
            border-bottom: 1px solid #f0f0f0; display: flex; align-items: center; gap: 8px;
            cursor: pointer; user-select: none; }
        .thinking-header .header-icon { font-size: 15px; }
        .thinking-header .header-text { flex: 1; }
        .thinking-header .header-toggle { font-size: 12px; color: #bbb; transition: transform 0.2s; }
        .thinking-panel.collapsed .header-toggle { transform: rotate(-90deg); }
        .thinking-header .pulse-dot { width: 7px; height: 7px; border-radius: 50%; background: #4a90d9; 
            animation: pulse 1.5s infinite; margin-right: 2px; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
        .thinking-body { display: flex; flex-direction: column; overflow: hidden; flex: 1; min-height: 0; }
        
        /* 进度条 */
        .thinking-progress { height: 3px; background: #f0f0f0; position: relative; overflow: hidden; }
        .thinking-progress .progress-fill { height: 100%; background: linear-gradient(90deg, #4a90d9, #6c5ce7);
            border-radius: 0 2px 2px 0; transition: width 0.4s ease; }
        
        /* 阶段标签 — 固定布局不跳动 */
        .thinking-stages { padding: 6px 14px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; flex-shrink: 0; }
        .thinking-stage { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #bbb;
            padding: 2px 8px; border-radius: 10px; background: #fafafa; transition: all 0.3s; }
        .thinking-stage.active { color: #4a90d9; background: #e8f0fe; font-weight: 600; }
        .thinking-stage.done { color: #52c41a; background: #f0fdf4; }
        .stage-icon { font-size: 12px; width: 14px; text-align: center; }
        .stage-icon.spin { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        
        /* LLM输出区域 — 固定高度，内容滚动 */
        .thinking-output { padding: 6px 14px 10px; font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
            font-size: 11px; color: #666; line-height: 1.6; white-space: pre-wrap; overflow-y: auto;
            flex: 1; min-height: 0; background: #fafbfc; border-top: 1px solid #f0f0f0; 
            scroll-behavior: smooth; }
        .thinking-output .cursor-blink { display: inline-block; width: 1px; height: 14px; 
            background: #4a90d9; margin-left: 2px; vertical-align: text-bottom; 
            animation: blink 0.8s infinite; }
        @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
        
        /* LLM 输出美化 */
        .llm-sentence { padding: 4px 0; }
        .llm-line { padding: 2px 0; font-size: 11px; color: #555; line-height: 1.6; }
        .llm-label { display: inline-block; padding: 0 5px; border-radius: 3px; font-size: 10px; 
            font-weight: 600; margin-right: 6px; min-width: 32px; text-align: center; }
        .llm-label:not(.error) { background: #e8f0fe; color: #4a90d9; }
        .llm-label.error { background: #fee2e2; color: #dc2626; }
        .llm-status { padding: 4px 0; font-size: 11px; color: #999; font-style: italic; }
        
        /* 完成提示 */
        .thinking-done-badge { display: none; align-items: center; gap: 4px; font-size: 11px; 
            color: #52c41a; padding: 4px 14px 8px; }
        .thinking-done-badge.show { display: flex; }
        
        /* ── Toast ── */
        .toast { position: fixed; top: 60px; right: 20px; background: #333; color: white; padding: 10px 20px;
                 border-radius: 8px; font-size: 13px; z-index: 300; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
        .toast.show { opacity: 1; }
        
        /* ── 图片Tab切换 ── */
        .img-tab { padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;
                   background: rgba(255,255,255,0.1); color: #ccc; border: 1px solid transparent; }
        .img-tab:hover { background: rgba(255,255,255,0.2); }
        .img-tab.active { background: rgba(74,144,217,0.3); color: white; border-color: #4a90d9; }
        .img-tab .tab-status { font-size: 10px; margin-left: 4px; }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>📝 AI 批改 — 标注编辑器</h1>
        <div class="nav-actions">
            <span id="imageTabs" style="display:none;display:flex;gap:4px;margin-right:12px;"></span>
            <button class="nav-btn" onclick="resetAll()">📷 重新上传</button>
            <button class="nav-btn" onclick="resetToAI()">🔄 重置AI标注</button>
            <button class="nav-btn" onclick="clearAllAnnotations()">🗑️ 清空标注</button>
            <button class="nav-btn" onclick="exportImage()">💾 导出图片</button>
            <button class="nav-btn primary" id="saveBtn" onclick="saveAnnotations()">✅ 保存标注</button>
        </div>
    </div>
    
    <div class="main-layout">
        <!-- 工具栏 -->
        <div class="toolbar" id="toolbar">
            <button class="tool-btn" data-tooltip="选择/移动 (V)" id="toolSelect" onclick="setTool('select')">🖱️</button>
            <div class="tool-separator"></div>
            <button class="tool-btn" data-tooltip="波浪线 — 精彩句 (W)" id="toolWavy" onclick="setTool('wavy')" style="color:#059669;">∼</button>
            <button class="tool-btn" data-tooltip="横线 — 问题句 (L)" id="toolLine" onclick="setTool('line')" style="color:#dc2626;">—</button>
            <button class="tool-btn" data-tooltip="★ 星星 — 点睛句 (S)" id="toolStar" onclick="setTool('star')" style="color:#d97706;">★</button>
            <div class="tool-separator"></div>
            <button class="tool-btn" data-tooltip="删除选中 (Del)" onclick="deleteSelected()">🗑️</button>
            <div class="tool-separator"></div>
            <button class="tool-btn" data-tooltip="撤销 (Ctrl+Z)" onclick="undo()">↩️</button>
            <button class="tool-btn" data-tooltip="重做 (Ctrl+Y)" onclick="redo()">↪️</button>
        </div>
        
        <!-- Canvas -->
        <div class="canvas-area" id="canvasArea">
            <div class="upload-overlay show" id="uploadOverlay">
                <div class="upload-card">
                    <div class="upload-icon">📷</div>
                    <h2>上传学生作业图片</h2>
                    <p>支持 JPG / PNG 格式，AI 自动批改并生成符号标注</p>
                    <form id="uploadForm" enctype="multipart/form-data">
                        <input type="file" id="fileInput" name="image" accept="image/*" multiple>
                        <div class="grader-options">
                            <div class="grader-option">
                                <input type="radio" id="graderFusion" name="grader" value="fusion" checked>
                                <label for="graderFusion">融合批改（推荐）</label>
                            </div>
                            <div class="grader-option">
                                <input type="radio" id="graderQwen" name="grader" value="qwen">
                                <label for="graderQwen">Qwen-VL-Max</label>
                            </div>
                            <div class="grader-option">
                                <input type="radio" id="graderBaidu" name="grader" value="baidu">
                                <label for="graderBaidu">百度手写OCR</label>
                            </div>
                            <div class="grader-option">
                                <input type="radio" id="graderVolcano" name="grader" value="volcano">
                                <label for="graderVolcano">融合批改-火山引擎</label>
                            </div>
                        </div>
                        <button type="button" class="upload-btn" onclick="document.getElementById('fileInput').click()">
                            选择图片并批改
                        </button>
                    </form>
                </div>
            </div>
            <div class="loading-overlay" id="loadingOverlay">
                <div style="text-align:center;">
                    <div class="spinner"></div>
                    <p style="margin-top:12px;color:#666;font-size:14px;">AI 正在批改中...</p>
                </div>
            </div>
            <div class="thinking-panel" id="thinkingPanel">
                <div class="thinking-header" onclick="toggleThinkingPanel()">
                    <span class="pulse-dot"></span>
                    <span class="header-icon">🤖</span>
                    <span class="header-text">AI 批改思考过程</span>
                    <span class="header-toggle">▾</span>
                </div>
                <div class="thinking-body">
                    <div class="thinking-progress"><div class="progress-fill" id="thinkingProgress" style="width:0%"></div></div>
                    <div class="thinking-stages" id="thinkingStages">
                        <div class="thinking-stage" id="stage-ocr"><span class="stage-icon">🔍</span>OCR识别</div>
                        <div class="thinking-stage" id="stage-rule"><span class="stage-icon">📐</span>规则初判</div>
                        <div class="thinking-stage" id="stage-llm"><span class="stage-icon">🧠</span>AI分析</div>
                        <div class="thinking-stage" id="stage-fuse"><span class="stage-icon">🔗</span>结果融合</div>
                    </div>
                    <div class="thinking-output" id="thinkingOutput"></div>
                    <div class="thinking-done-badge" id="thinkingDoneBadge">✅ 批改完成</div>
                </div>
            </div>
            <canvas id="annotationCanvas"></canvas>
            <div class="status-bar" id="statusBar">
                <span id="statusZoom">100%</span>
                <span id="statusAnns">标注: 0</span>
                <span id="statusCoords"></span>
            </div>
        </div>
        
        <!-- 侧边面板 -->
        <div class="side-panel" id="sidePanel">
            <div class="panel-tabs">
                <div class="panel-tab active" id="tabAnnotations" onclick="window.sidePanel.switchTab('annotations')">📋 标注列表</div>
                <div class="panel-tab" id="tabReport" onclick="window.sidePanel.switchTab('report')">📊 批改报告</div>
            </div>
            <div class="panel-body" id="panelAnnotations">
                <div class="panel-header">
                    标注列表
                    <span class="panel-count" id="panelCount">0 个</span>
                </div>
                <div class="annotation-list" id="annotationList"></div>
                <div class="edit-panel" id="editPanel">
                    <label>标注类型</label>
                    <select id="editType" onchange="onEditTypeChange()">
                        <option value="wavy">～～ 波浪线（精彩句）</option>
                        <option value="line">—— 横线（问题句）</option>
                        <option value="star">★ 星星（点睛句）</option>
                    </select>
                    <label>批注文字</label>
                    <textarea id="editComment" placeholder="输入批注说明..."></textarea>
                    <div class="edit-actions">
                        <button class="edit-btn save" onclick="saveEdit()">保存</button>
                        <button class="edit-btn cancel" onclick="cancelEdit()">取消</button>
                        <button class="edit-btn delete" onclick="deleteSelected()" style="margin-left:auto;">删除</button>
                    </div>
                </div>
            </div>
            <div class="panel-body" id="panelReport" style="display:none;">
                <div class="grading-report" id="gradingReport">
                    <div class="report-empty">选择图片后查看批改报告</div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- 上下文菜单 -->
    <div class="context-menu" id="contextMenu">
        <div class="menu-item" onclick="contextSwitchType('wavy')">～～ 改为波浪线</div>
        <div class="menu-item" onclick="contextSwitchType('line')">—— 改为横线</div>
        <div class="menu-item" onclick="contextSwitchType('star')">★ 改为星星</div>
        <div class="menu-divider"></div>
        <div class="menu-item danger" onclick="deleteSelected()">🗑️ 删除</div>
    </div>
    
    <!-- Toast -->
    <div class="toast" id="toast"></div>
    
    <script>
    // ═══════════════════════════════════════════════
    // 全局状态
    // ═══════════════════════════════════════════════
    let canvas = null;
    let fabricCanvas = null;
    let currentTool = 'select';
    let selectedAnnId = null;
    let annotations = [];
    let undoStack = [];
    let redoStack = [];
    let taskId = null;
    let originalImage = null;
    
    {% if result %}
    // 批改结果数据
    window.__gradingData = {
        total_score: {{ result.total_score }},
        total_errors: {{ result.total_errors }},
        overall_comment: {{ (result.overall_comment or "") | tojson }},
        annotations: {{ annotations_json | safe }},
        homework_completion: {{ (result.homework_completion or "") | tojson }},
        dimension_scores: {{ (result.dimension_scores or {}) | tojson }},
        strengths: {{ (result.strengths or []) | tojson }},
        weaknesses: {{ (result.weaknesses or []) | tojson }},
        suggestions: {{ (result.suggestions or []) | tojson }},
        highlight_sentences: {{ (result.highlight_sentences or []) | tojson }},
        parent_feedback: {{ (result.parent_feedback or "") | tojson }},
        system_tags: {{ (result.system_tags or []) | tojson }}
    };
    window.__imageB64 = "{{ image_b64 }}";
    {% endif %}
    </script>
    
    <script src="/static/js/core/UndoManager.js"></script>
    <script src="/static/js/core/AnnotationStore.js"></script>
    <script src="/static/js/annotations/WavyLine.js"></script>
    <script src="/static/js/annotations/StraightLine.js"></script>
    <script src="/static/js/annotations/StarAnnotation.js"></script>
    <script src="/static/js/core/CanvasManager.js"></script>
    <script src="/static/js/components/SidePanel.js"></script>
    <script src="/static/js/components/GradingReportPanel.js"></script>
    <script src="/static/js/app.js"></script>
</body>
</html>
"""


@app.route("/")
def index():
    """首页"""
    return render_template_string(HTML_TEMPLATE)


@app.route("/grade", methods=["POST"])
def grade():
    """执行批改 — 返回完整HTML页面（用于直接表单提交）"""
    return _do_grade(request, return_html=True)


@app.route("/grade_json", methods=["POST"])
def grade_json():
    """执行批改 — 返回JSON数据（用于AJAX调用）"""
    return _do_grade(request, return_html=False)


@app.route("/grade_stream", methods=["POST"])
def grade_stream():
    """流式批改 — SSE端点，实时推送批改进度和LLM输出"""
    if "image" not in request.files:
        return {"error": "未上传图片"}, 400

    file = request.files["image"]
    if file.filename == "":
        return {"error": "未选择文件"}, 400

    grader_name = request.form.get("grader", "fusion")

    # 保存图片
    upload_dir = PROJECT_ROOT / "output" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / file.filename
    file.save(input_path)

    grading_input = GradingInput(
        image_path=str(input_path),
        textbook_name="小石潭记",
        textbook_author="柳宗元",
    )

    def generate():
        try:
            grader = get_grader(grader_name)

            # 检查是否支持流式
            if not hasattr(grader, 'grade_stream'):
                # fallback: 同步批改
                yield f"data: {json.dumps({'type': 'stage', 'stage': 'processing', 'message': '正在批改...'}, ensure_ascii=False)}\n\n"
                result = grader.grade(grading_input)
                from utils.annotation_utils import generate_annotations_from_result, annotations_to_dict_list
                annotations = generate_annotations_from_result(result)
                yield f"data: {json.dumps({'type': 'result', 'data': _build_result_dict(result, annotations)}, ensure_ascii=False)}\n\n"
                return

            for event in grader.grade_stream(grading_input):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


def _build_result_dict(result, annotations):
    """构建结果字典，用于流式返回"""
    from utils.annotation_utils import annotations_to_dict_list
    return {
        "total_score": result.total_score,
        "total_errors": result.total_errors,
        "overall_comment": result.overall_comment,
        "homework_completion": result.homework_completion,
        "dimension_scores": result.dimension_scores,
        "dimension_analysis": getattr(result, 'dimension_analysis', {}),
        "strengths": result.strengths,
        "weaknesses": result.weaknesses,
        "suggestions": result.suggestions,
        "highlight_sentences": result.highlight_sentences,
        "parent_feedback": result.parent_feedback,
        "system_tags": result.system_tags,
        "grader_name": result.grader_name,
        "processing_time_ms": result.processing_time_ms,
        "annotations": annotations_to_dict_list(annotations),
    }


def _do_grade(request, return_html=True):
    """批改核心逻辑"""
    if "image" not in request.files:
        if return_html:
            return render_template_string(HTML_TEMPLATE, error="未上传图片")
        return {"error": "未上传图片"}, 400
    
    file = request.files["image"]
    if file.filename == "":
        if return_html:
            return render_template_string(HTML_TEMPLATE, error="未选择文件")
        return {"error": "未选择文件"}, 400
    
    grader_name = request.form.get("grader", "qwen")
    print(f"[DEBUG] 选择的批改策略: {grader_name}")
    
    try:
        # 保存上传的图片
        upload_dir = PROJECT_ROOT / "output" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        input_path = upload_dir / file.filename
        file.save(input_path)
        
        # 获取批改策略
        grader = get_grader(grader_name)
        ok, msg = grader.validate()
        if not ok:
            if return_html:
                return render_template_string(HTML_TEMPLATE, error=f"策略不可用: {msg}")
            return {"error": f"策略不可用: {msg}"}, 400
        
        # 构建输入
        grading_input = GradingInput(
            image_path=str(input_path),
            textbook_name="小石潭记",
            textbook_author="柳宗元",
        )
        
        # 执行批改
        result = grader.grade(grading_input)
        
        # 生成标注数据
        if not result.annotations:
            result.annotations = generate_annotations_from_result(result)
        print(f"[DEBUG] sentence_analyses: {len(result.sentence_analyses)}句, annotations: {len(result.annotations)}个")
        for i, sa in enumerate(result.sentence_analyses[:3]):
            print(f"  句{i}: errors={len(sa.errors)}, bbox={sa.bbox}, excellent={sa.is_excellent}, highlight={sa.is_highlight}")
        
        # 渲染批改完成图（兼容旧版）— 但前端标注编辑器使用原图
        output_path = upload_dir / f"graded_{file.filename}"
        renderer = GradingRenderer()
        renderer.render(str(input_path), result, str(output_path))
        
        # 读取原图为 base64（前端Canvas标注编辑器使用原图）
        with open(input_path, "rb") as f:
            original_image_b64 = base64.b64encode(f.read()).decode("utf-8")
        
        # 读取旧版渲染图为 base64（兼容旧版直接展示）
        with open(output_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        
        # 标注数据 JSON
        annotations_json = json.dumps(
            annotations_to_dict_list(result.annotations),
            ensure_ascii=False
        )
        
        # 生成 JSON 报告
        json_report = json.dumps({
            "grader": result.grader_name,
            "total_score": result.total_score,
            "total_errors": result.total_errors,
            "total_deductions": result.total_deductions,
            "confidence": result.confidence.value,
            "status": result.status.value,
            "processing_time_ms": result.processing_time_ms,
            "overall_comment": result.overall_comment,
            "recognized_text": result.recognized_text,
            "homework_completion": result.homework_completion,
            "dimension_scores": result.dimension_scores,
            "strengths": result.strengths,
            "weaknesses": result.weaknesses,
            "suggestions": result.suggestions,
            "highlight_sentences": result.highlight_sentences,
            "parent_feedback": result.parent_feedback,
            "system_tags": result.system_tags,
            "annotations": annotations_to_dict_list(result.annotations),
            "annotation_version": result.annotation_version,
            "sentence_analyses": [
                {
                    "original_classical": sa.original_classical,
                    "student_translation": sa.student_translation,
                    "standard_translation": sa.standard_translation,
                    "sentence_score": sa.sentence_score,
                    "is_excellent": sa.is_excellent,
                    "is_highlight": sa.is_highlight,
                    "highlight_comment": sa.highlight_comment,
                    "errors": [
                        {
                            "error_type": e.error_type.value,
                            "original_text": e.original_text,
                            "correct_text": e.correct_text,
                            "reason": e.reason,
                            "deduction_points": e.deduction_points,
                            "bbox": e.bbox.to_list() if e.bbox else None,
                        }
                        for e in sa.errors
                    ],
                }
                for sa in result.sentence_analyses
            ],
        }, ensure_ascii=False, indent=2)
        
        # 保存 JSON 报告到文件
        json_path = str(output_path).replace(".jpg", "_report.json").replace(".png", "_report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json_report)
        
        if return_html:
            return render_template_string(
                HTML_TEMPLATE,
                result=result,
                image_b64=image_b64,
                annotations_json=annotations_json,
                json_report=json_report,
            )
        
        # JSON 返回 — 前端标注编辑器使用原图
        return {
            "ok": True,
            "image_b64": original_image_b64,
            "annotations": annotations_to_dict_list(result.annotations),
            "grading_result": {
                "total_score": result.total_score,
                "total_errors": result.total_errors,
                "total_deductions": result.total_deductions,
                "confidence": result.confidence.value,
                "overall_comment": result.overall_comment,
                "homework_completion": result.homework_completion,
                "dimension_scores": result.dimension_scores,
                "strengths": result.strengths,
                "weaknesses": result.weaknesses,
                "suggestions": result.suggestions,
                "highlight_sentences": result.highlight_sentences,
                "parent_feedback": result.parent_feedback,
                "system_tags": result.system_tags,
            },
            "json_report": json_report,
        }
        
    except Exception as e:
        import traceback
        if return_html:
            return render_template_string(
                HTML_TEMPLATE,
                error=f"{str(e)}\n\n{traceback.format_exc()}",
            )
        return {"error": str(e), "traceback": traceback.format_exc()}, 500


# ── 标注数据 API ────────────────────────────────────

# 内存存储（生产环境应替换为数据库）
_annotation_store: dict = {}  # task_id -> List[dict]


@app.route("/api/annotations/<task_id>", methods=["GET"])
def api_get_annotations(task_id):
    """获取标注数据"""
    anns = _annotation_store.get(task_id, [])
    return {"annotations": anns, "version": len(anns) and 1 or 0}


@app.route("/api/annotations/<task_id>", methods=["PUT"])
def api_save_annotations(task_id):
    """保存标注数据"""
    data = request.get_json()
    if not data or "annotations" not in data:
        return {"error": "缺少 annotations 字段"}, 400
    
    _annotation_store[task_id] = data["annotations"]
    print(f"[DEBUG] 保存标注: task={task_id}, count={len(data['annotations'])}")
    return {"ok": True, "count": len(data["annotations"])}


@app.route("/api/annotations/<task_id>/export", methods=["POST"])
def api_export_image(task_id):
    """导出带标注的图片（前端已支持 Canvas.toDataURL，此接口为备选）"""
    return {"ok": True, "message": "请使用前端导出功能"}


@app.route("/static/<path:filename>")
def serve_static(filename):
    """静态文件服务 — 禁用缓存确保JS更新即时生效"""
    from flask import send_from_directory, make_response
    static_dir = PROJECT_ROOT / "static"
    response = make_response(send_from_directory(str(static_dir), filename))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route("/download")
def download_file():
    """文件下载端点，用于下载项目产物"""
    import urllib.parse
    filename = request.args.get("file", "ai-grader-package.tar.gz")
    filepath = os.path.join("/workspace", filename)
    if not os.path.exists(filepath):
        return {"error": f"文件不存在: {filename}"}, 404
    from flask import send_file
    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route("/downloads")
def downloads_page():
    """下载页面"""
    import os as _os
    files = []
    for f in sorted(_os.listdir("/workspace")):
        fp = _os.path.join("/workspace", f)
        if _os.path.isfile(fp) and not f.startswith('.'):
            size_kb = _os.path.getsize(fp) // 1024
            files.append({"name": f, "size_kb": size_kb})
    
    items_html = ""
    for f in files:
        items_html += f'''
        <div class="card">
            <div class="icon">{'📦' if '.tar.gz' in f['name'] else '📄' if '.md' in f['name'] else '🖼' if f['name'].endswith('.png') else '📁'}</div>
            <div class="info">
                <div class="name">{f['name']}</div>
                <div class="meta">{f['size_kb']}KB</div>
            </div>
            <a class="btn" href="/download?file={f['name']}" download>⬇ 下载</a>
        </div>'''
    
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>项目文件下载</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#f5f5f5; padding:40px 20px; }}
.container {{ max-width:700px; margin:0 auto; }}
h1 {{ font-size:24px; margin-bottom:8px; }}
p.sub {{ color:#666; margin-bottom:30px; }}
.card {{ background:#fff; border-radius:12px; padding:20px 24px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.08); display:flex; align-items:center; gap:16px; }}
.card:hover {{ box-shadow:0 4px 12px rgba(0,0,0,0.12); }}
.icon {{ font-size:32px; }}
.info {{ flex:1; }}
.name {{ font-size:15px; font-weight:600; margin-bottom:4px; word-break:break-all; }}
.meta {{ font-size:13px; color:#888; }}
.btn {{ display:inline-block; padding:10px 18px; background:#1a73e8; color:#fff; text-decoration:none; border-radius:8px; font-size:14px; font-weight:500; white-space:nowrap; }}
.btn:hover {{ background:#1557b0; }}
.footer {{ text-align:center; color:#999; font-size:13px; margin-top:40px; }}
</style>
</head>
<body>
<div class="container">
<h1>📦 AI 批改系统 — 项目文件下载</h1>
<p class="sub">点击下载，可交给其他 AI 工具继续协作开发</p>
{items_html}
<p class="footer">直接点击「下载」按钮即可保存到本地</p>
</div>
</body>
</html>'''


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 AI 批改 PoC Web 服务启动")
    print("=" * 50)
    print("访问地址: http://localhost:8080")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
