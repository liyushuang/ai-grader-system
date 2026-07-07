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
if not os.environ.get("VOLCANO_API_KEY"):
    os.environ["VOLCANO_API_KEY"] = "ark-ddbae8e5-c1ad-4200-8b1d-b8483adca0c6-9eda7"

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
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; 
               background: #f4f6f8; height: 100vh; overflow: hidden; color: #1f2937; }
        
        /* ── 顶部导航栏 ── */
        .navbar { background: rgba(255,255,255,0.96); color: #111827; padding: 0 18px; height: 54px;
                  display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #e5e7eb;
                  box-shadow: 0 1px 8px rgba(15,23,42,0.05); }
        .navbar h1 { font-size: 15px; font-weight: 700; }
        .navbar .nav-actions { display: flex; gap: 8px; align-items: center; }
        .nav-btn { background: #f3f4f6; color: #374151; border: 1px solid #e5e7eb; 
                   padding: 7px 13px; border-radius: 7px; cursor: pointer; font-size: 13px; font-weight: 600;
                   transition: all 0.18s ease; }
        .nav-btn:hover { background: #eaf2ff; border-color: #bfdbfe; color: #1d4ed8; transform: translateY(-1px); }
        .nav-btn.primary { background: #2563eb; color: white; border-color: #2563eb; }
        .nav-btn.primary:hover { background: #1d4ed8; color: white; }
        .nav-btn.danger { background: #fee2e2; color: #b91c1c; border-color: #fecaca; }
        
        /* ── 主布局 ── */
        .main-layout { display: flex; height: calc(100vh - 54px); background: #f4f6f8; }
        .main-layout.empty .side-by-side-panel,
        .main-layout.empty .side-panel { display: none; }
        .main-layout.empty .canvas-area { align-items: center; }
        .main-layout.empty .canvas-container { display: none !important; }
        
        /* ── 工具栏 ── */
        .toolbar { position: fixed; left: 50%; bottom: 16px; transform: translateX(-50%); height: 56px;
                   background: rgba(31,41,55,0.96); border: 1px solid rgba(255,255,255,0.12);
                   display: flex; flex-direction: row; align-items: center; padding: 8px 12px; gap: 6px;
                   border-radius: 10px; box-shadow: 0 12px 32px rgba(15,23,42,0.28); z-index: 80; }
        .tool-btn { width: 42px; height: 42px; border: 1px solid transparent; border-radius: 8px;
                    background: transparent; color: #e5e7eb; cursor: pointer; display: flex; align-items: center; 
                    justify-content: center; font-size: 18px; transition: all 0.18s; position: relative; }
        .tool-btn:hover { background: rgba(255,255,255,0.1); border-color: rgba(255,255,255,0.12); }
        .tool-btn.active { background: #2563eb; border-color: #60a5fa; box-shadow: 0 8px 18px rgba(37,99,235,0.32); }
        .tool-btn[data-tooltip]:hover::after { content: attr(data-tooltip); position: absolute;
            bottom: 50px; left: 50%; transform: translateX(-50%); background: #111827; color: white; padding: 5px 8px; border-radius: 5px;
            font-size: 11px; white-space: nowrap; z-index: 100; pointer-events: none; }
        .tool-separator { width: 1px; height: 28px; background: rgba(255,255,255,0.16); margin: 0 4px; }
        
        /* ── Canvas 区域 ── */
        .canvas-area { flex: 1 1 auto; min-width: 500px; display: flex; flex-direction: column; align-items: flex-end; justify-content: center;
                       background: #eef2f6; overflow: hidden; position: relative; padding: 20px 24px 78px 24px; }
        .canvas-container, .canvas-container canvas, #annotationCanvas { box-shadow: 0 10px 28px rgba(15,23,42,0.14); border-radius: 2px; }
        .canvas-upload-hint { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
            text-align: center; color: #999; pointer-events: none; }
        .canvas-upload-hint .hint-icon { font-size: 48px; margin-bottom: 10px; }
        .canvas-upload-hint p { font-size: 14px; }
        
        /* ── 侧边面板 ── */
        .side-panel { width: 340px; background: white; border-left: 1px solid #e5e7eb;
                      display: flex; flex-direction: column; overflow: hidden; }
        
        /* ── 旁批面板 ── */
        .side-by-side-panel {
            width: 390px;
            background: #ffffff;
            border-left: 1px solid #e5e7eb;
            position: relative;
            overflow-y: auto;
            overflow-x: hidden;
            flex-shrink: 0;
            height: 100%;
            padding-right: 18px;
        }
        .side-by-side-panel::before {
            content: '详细点评';
            position: sticky;
            top: 0;
            display: block;
            padding: 16px 22px 12px 44px;
            background: rgba(255,255,255,0.94);
            backdrop-filter: blur(8px);
            color: #2563eb;
            font-size: 13px;
            font-weight: 700;
            z-index: 3;
            border-bottom: 1px solid #eef2f7;
        }
        .side-card {
            position: absolute;
            width: calc(100% - 58px);
            left: 42px;
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 9px 10px;
            box-shadow: none;
            transition: all 0.2s ease;
            cursor: pointer;
            z-index: 2;
        }
        .side-card:hover {
            background: #f8fafc;
            border-color: #e5e7eb;
        }
        .side-card.selected {
            border-color: #93c5fd;
            box-shadow: 0 0 0 3px rgba(37,99,235,0.10);
            background: #f8fbff;
        }
        .side-card .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 4px;
        }
        .side-card .card-number {
            position: absolute;
            left: -30px;
            top: 12px;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: #60a5fa;
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: 700;
            box-shadow: 0 4px 12px rgba(37,99,235,0.22);
        }
        .side-card .card-badge {
            width: 22px;
            height: 22px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: bold;
            color: white;
        }
        .side-card .card-badge.wavy { background: #10b981; }
        .side-card .card-badge.line { background: #ef4444; }
        .side-card .card-badge.star { background: #f59e0b; }
        .side-card .card-type {
            font-size: 12px;
            font-weight: 600;
        }
        .side-card .card-type.wavy { color: #059669; }
        .side-card .card-type.line { color: #dc2626; }
        .side-card .card-type.star { color: #d97706; }
        .side-card .card-comment {
            font-size: 19px;
            color: #ef2f2f;
            line-height: 1.7;
            font-weight: 700;
            word-break: break-word;
            font-family: 'Kaiti SC', 'STKaiti', 'KaiTi', 'PingFang SC', serif;
            text-wrap: pretty;
        }
        .side-card .card-meta {
            margin-top: 4px;
            font-size: 11px;
            color: #94a3b8;
            display: flex;
            justify-content: space-between;
        }

        /* ── 报告面板增强样式 ── */
        .style-switcher {
            display: flex;
            gap: 6px;
            margin-bottom: 10px;
            background: #f1f5f9;
            padding: 4px;
            border-radius: 8px;
        }
        .style-btn {
            flex: 1;
            padding: 6px 8px;
            border: none;
            background: transparent;
            font-size: 11.5px;
            font-weight: 500;
            color: #64748b;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.15s;
            text-align: center;
        }
        .style-btn:hover {
            color: #334155;
        }
        .style-btn.active {
            background: white;
            color: #1a73e8;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            font-weight: 600;
        }
        .report-score-box {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 16px 0;
            border-bottom: 1px solid #f1f5f9;
            margin-bottom: 16px;
        }
        .rating-badge {
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: bold;
            font-size: 13px;
            color: white;
        }
        .rating-badge.level-优 { background: #10b981; }
        .rating-badge.level-良 { background: #3b82f6; }
        .rating-badge.level-中 { background: #f59e0b; }
        .rating-badge.level-差 { background: #ef4444; }
        
        .textarea-editable {
            width: 100%;
            height: 120px;
            border: 1.5px solid #e2e8f0;
            border-radius: 8px;
            padding: 10px;
            font-size: 12px;
            line-height: 1.6;
            color: #334155;
            resize: vertical;
            font-family: inherit;
            margin-bottom: 12px;
        }
        .textarea-editable:focus {
            outline: none;
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59,130,246,0.15);
        }
        .parent-feedback-box {
            background: #faf5ff;
            border-left: 3.5px solid #a855f7;
            padding: 10px 12px;
            border-radius: 0 8px 8px 0;
            margin-bottom: 16px;
        }
        
        /* ── 全文润色样式 ── */
        .polished-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px;
            font-size: 12.5px;
            line-height: 1.7;
            color: #334155;
            margin-bottom: 16px;
            white-space: pre-wrap;
        }
        .comparison-item {
            border-bottom: 1px solid #f1f5f9;
            padding: 12px 0;
        }
        .comparison-item:last-child {
            border-bottom: none;
        }
        .comp-lbl {
            font-size: 10px;
            font-weight: 700;
            color: #94a3b8;
            margin-bottom: 2px;
            display: inline-block;
        }
        .comp-val {
            font-size: 12px;
            line-height: 1.6;
            color: #334155;
            margin-bottom: 6px;
        }
        .comp-val.original {
            color: #64748b;
            font-weight: 500;
        }
        .comp-val.student {
            color: #334155;
        }
        .comp-val.polished {
            color: #10b981;
            font-weight: 500;
            background: #f0fdf4;
            padding: 4px 6px;
            border-radius: 4px;
            display: inline-block;
            width: 100%;
        }
        .comp-errs {
            background: #fff5f5;
            border-left: 2.5px solid #f87171;
            padding: 6px 8px;
            border-radius: 0 4px 4px 0;
            font-size: 11px;
            color: #b91c1c;
            line-height: 1.4;
        }
        
        .panel-tabs { display: flex; border-bottom: 1px solid #e5e7eb; flex-shrink: 0; padding: 8px 10px 0; gap: 6px; }
        .panel-tab { flex: 1; padding: 9px 8px; text-align: center; font-size: 12px; font-weight: 600;
                     color: #999; cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s; }
        .panel-tab:hover { color: #374151; background: #f9fafb; border-radius: 8px 8px 0 0; }
        .panel-tab.active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 700; }
        .panel-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .report-panel-title { padding: 12px 16px; border-bottom: 1px solid #e5e7eb;
            color: #2563eb; font-size: 14px; font-weight: 800; background: #fff; }
        .panel-header { padding: 10px 14px; border-bottom: 1px solid #f0f0f0; 
                        font-weight: 600; font-size: 13px; color: #333; 
                        display: flex; justify-content: space-between; align-items: center; }
        .panel-count { font-size: 12px; color: #999; font-weight: normal; }
        .annotation-list { flex: 1; overflow-y: auto; padding: 8px 10px; }
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
        .edit-modal-backdrop { position: fixed; inset: 0; background: rgba(15,23,42,0.28);
            z-index: 180; display: none; align-items: center; justify-content: center; padding: 24px; }
        .edit-modal-backdrop.active { display: flex; }
        .edit-panel { width: min(420px, calc(100vw - 48px)); padding: 16px; border: 1px solid #dbeafe; display: none; flex-shrink: 0;
            background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%); box-shadow: 0 18px 46px rgba(15,23,42,0.22);
            border-radius: 10px; }
        .edit-modal-backdrop.active .edit-panel { display: block; }
        .edit-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;
            color: #1f2937; font-size: 13px; font-weight: 800; }
        .edit-hint { color: #94a3b8; font-size: 11px; font-weight: 600; }
        .edit-panel label { font-size: 12px; font-weight: 700; color: #334155; display: block; margin-bottom: 5px; }
        .edit-panel select, .edit-panel textarea { width: 100%; border: 1px solid #ddd; border-radius: 6px; 
            padding: 8px 10px; font-size: 13px; margin-bottom: 10px; font-family: inherit; }
        .edit-panel select:focus, .edit-panel textarea:focus { outline: none; border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,0.12); }
        .edit-panel textarea { height: 96px; resize: vertical; line-height: 1.55; }
        .edit-panel .edit-actions { display: flex; gap: 8px; }
        .edit-btn { padding: 7px 14px; border-radius: 7px; border: none; cursor: pointer; font-size: 12px; font-weight: 700; }
        .edit-btn.save { background: #2563eb; color: white; }
        .edit-btn.cancel { background: #f0f0f0; color: #666; }
        .edit-btn.delete { background: #fee2e2; color: #dc2626; }
        .edit-close { border: none; background: #f1f5f9; color: #64748b; width: 26px; height: 26px;
            border-radius: 7px; cursor: pointer; font-size: 16px; line-height: 1; }
        .edit-close:hover { background: #e2e8f0; color: #334155; }
        
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
        .report-copy-row { display: flex; gap: 8px; margin: 0 0 12px; }
        .copy-btn { flex: 1; border: 1px solid #dbeafe; background: #eff6ff; color: #2563eb;
            border-radius: 7px; padding: 7px 6px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .copy-btn:hover { background: #dbeafe; }
        .deliverable-section { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
            padding: 12px; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(15,23,42,0.04); }
        .deliverable-head { display: flex; align-items: center; justify-content: space-between;
            color: #111827; font-size: 14px; font-weight: 800; margin-bottom: 8px; }
        .copy-link { border: none; background: transparent; color: #2563eb; font-size: 12px;
            font-weight: 700; cursor: pointer; padding: 2px 0; }
        .copy-link:hover { color: #1d4ed8; text-decoration: underline; }
        .deliverable-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
        .deliverable-list li { font-size: 13px; line-height: 1.65; color: #374151; background: #f9fafb;
            border-left: 3px solid #93c5fd; border-radius: 0 7px 7px 0; padding: 8px 10px; }
        .deliverable-empty { font-size: 12px; line-height: 1.6; color: #9ca3af; background: #f9fafb;
            border-radius: 7px; padding: 10px; }
        .deliverable-textarea { min-height: 112px; margin-bottom: 0; background: #f9fafb; border-color: #e5e7eb; }
        .deliverable-textarea.parent { min-height: 92px; }
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
        .status-bar { position: absolute; bottom: 0; left: 0; right: 0; height: 28px;
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
        .thinking-panel { display: none; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            width: min(640px, calc(100% - 72px)); margin: 0;
            background: #fff; border: 1px solid #e8ecf1; border-radius: 10px;
            box-shadow: 0 14px 40px rgba(15,23,42,0.12); flex-direction: column; overflow: hidden;
            height: min(360px, calc(100% - 120px)); flex-shrink: 0; transition: all 0.3s ease; z-index: 35; }
        .thinking-panel.show { display: flex; }
        .thinking-panel.collapsed .thinking-body { display: none; }
        .thinking-panel.collapsed { height: 38px; }
        .thinking-header { padding: 12px 18px; font-size: 15px; font-weight: 700; color: #333;
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
        .thinking-stages { padding: 10px 18px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; flex-shrink: 0; }
        .thinking-stage { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #94a3b8;
            padding: 4px 10px; border-radius: 12px; background: #fafafa; transition: all 0.3s; }
        .thinking-stage.active { color: #4a90d9; background: #e8f0fe; font-weight: 600; }
        .thinking-stage.done { color: #52c41a; background: #f0fdf4; }
        .stage-icon { font-size: 12px; width: 14px; text-align: center; }
        .stage-icon.spin { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        
        /* LLM输出区域 — 固定高度，内容滚动 */
        .thinking-output { padding: 12px 18px 14px; font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
            font-size: 13px; color: #475569; line-height: 1.7; white-space: pre-wrap; overflow-y: auto;
            flex: 1; min-height: 0; background: #fafbfc; border-top: 1px solid #f0f0f0; 
            scroll-behavior: smooth; }
        .thinking-output .cursor-blink { display: inline-block; width: 1px; height: 14px; 
            background: #4a90d9; margin-left: 2px; vertical-align: text-bottom; 
            animation: blink 0.8s infinite; }
        @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
        
        /* LLM 输出美化 */
        .llm-sentence { padding: 4px 0; }
        .llm-line { padding: 3px 0; font-size: 13px; color: #334155; line-height: 1.7; }
        .llm-label { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 11px; 
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
        .img-tab { padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px;
                   background: #f3f4f6; color: #6b7280; border: 1px solid #e5e7eb; }
        .img-tab:hover { background: #eaf2ff; color: #1d4ed8; }
        .img-tab.active { background: #dbeafe; color: #1d4ed8; border-color: #93c5fd; }
        .img-tab .tab-status { font-size: 10px; margin-left: 4px; }

        @media (max-width: 1500px) {
            .side-by-side-panel { width: 360px; }
            .side-card .card-comment { font-size: 18px; }
            .side-panel { width: 330px; }
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>📝 AI 批改 — 标注编辑器</h1>
        <div class="nav-actions">
            <span id="imageTabs" style="display:none;display:flex;gap:4px;margin-right:12px;"></span>
            <button class="nav-btn" onclick="location.href='/demo'">🧪 样式Demo</button>
            <button class="nav-btn" onclick="resetAll()">📷 重新上传</button>
            <button class="nav-btn" onclick="resetToAI()">🔄 重置AI标注</button>
            <button class="nav-btn" onclick="clearAllAnnotations()">🗑️ 清空标注</button>
            <button class="nav-btn" onclick="exportImage()">💾 导出图片</button>
            <button class="nav-btn primary" id="saveBtn" onclick="saveAnnotations()">✅ 保存标注</button>
        </div>
    </div>
    
    <div class="main-layout empty" id="mainLayout">
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
                                <label for="graderFusion">千问（推荐·OCR+规则+文本复核）</label>
                            </div>
                            <div class="grader-option">
                                <input type="radio" id="graderVolcano" name="grader" value="volcano">
                                <label for="graderVolcano">火山</label>
                            </div>
                            <div class="grader-option">
                                <input type="radio" id="graderQwen" name="grader" value="qwen">
                                <label for="graderQwen">Qwen-VL-Max（视觉理解方案）</label>
                            </div>
                            <div class="grader-option">
                                <input type="radio" id="graderBaidu" name="grader" value="baidu">
                                <label for="graderBaidu">百度手写OCR</label>
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
        <!-- 旁批面板 -->
        <div class="side-by-side-panel" id="sideBySidePanel">
            <svg id="sideBySideLines" style="position:absolute; top:0; left:0; width:100%; height:100%; pointer-events:none; z-index:1;"></svg>
        </div>

        <!-- 侧边面板 -->
        <div class="side-panel" id="sidePanel">
            <div class="report-panel-title">📊 批改报告</div>
            <div class="panel-body" id="panelReport">
                <div class="grading-report" id="gradingReport">
                    <div class="report-empty">选择图片后查看批改报告</div>
                </div>
            </div>
        </div>
    </div>

    <div class="edit-modal-backdrop" id="editModal" onclick="if(event.target===this) cancelEdit()">
        <div class="edit-panel" id="editPanel">
            <div class="edit-title">
                <span>当前批注</span>
                <button class="edit-close" onclick="cancelEdit()" title="关闭">×</button>
            </div>
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
        overall_comment_general: {{ (result.overall_comment_general or result.overall_comment or "") | tojson }},
        overall_comment_encouraging: {{ (result.overall_comment_encouraging or "") | tojson }},
        overall_comment_instructive: {{ (result.overall_comment_instructive or "") | tojson }},
        polished_full_translation: {{ (result.polished_full_translation or "") | tojson }},
        annotations: {{ annotations_json | safe }},
        homework_completion: {{ (result.homework_completion or "") | tojson }},
        dimension_scores: {{ (result.dimension_scores or {}) | tojson }},
        dimension_analysis: {{ (result.dimension_analysis or {}) | tojson }},
        strengths: {{ (result.strengths or []) | tojson }},
        weaknesses: {{ (result.weaknesses or []) | tojson }},
        suggestions: {{ (result.suggestions or []) | tojson }},
        highlight_sentences: {{ (result.highlight_sentences or []) | tojson }},
        parent_feedback: {{ (result.parent_feedback or "") | tojson }},
        system_tags: {{ (result.system_tags or []) | tojson }},
        sentence_analyses: {{ sentence_analyses_json | safe }}
    };
    window.__imageB64 = "{{ image_b64 }}";
    {% endif %}
    {% if demo_json %}
    window.__demoSession = {{ demo_json | safe }};
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


@app.route("/demo")
def demo():
    """样式调试页：直接加载 test_data 的固定批改结果，不调用 AI。"""
    demo_data = _build_demo_session()
    return render_template_string(
        HTML_TEMPLATE,
        demo_json=json.dumps(demo_data, ensure_ascii=False),
    )


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
        "overall_comment_general": result.overall_comment_general,
        "overall_comment_encouraging": result.overall_comment_encouraging,
        "overall_comment_instructive": result.overall_comment_instructive,
        "polished_full_translation": result.polished_full_translation,
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
        "sentence_analyses": [
            {
                "original_classical": sa.original_classical,
                "student_translation": sa.student_translation,
                "standard_translation": sa.standard_translation,
                "polished_translation": sa.polished_translation,
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
        ]
    }


def _build_demo_session():
    """构造本地样式调试数据，避免每次等待模型批改。"""
    demo_image = PROJECT_ROOT / "test_data" / "dbj2483646-未点评习作-第1张.jpg"
    with open(demo_image, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    annotations = [
        {
            "id": "demo_ann_1",
            "type": "line",
            "start_x": 70,
            "start_y": 170,
            "end_x": 760,
            "end_y": 170,
            "source": "ai",
            "sentence_index": 0,
            "error_index": 0,
            "comment": "补充主语：我/我们/我和我的朋友们",
        },
        {
            "id": "demo_ann_2",
            "type": "line",
            "start_x": 500,
            "start_y": 318,
            "end_x": 640,
            "end_y": 318,
            "source": "ai",
            "sentence_index": 1,
            "error_index": 1,
            "comment": "佩环：腰间玉佩和玉环相碰撞",
        },
        {
            "id": "demo_ann_3",
            "type": "line",
            "start_x": 680,
            "start_y": 450,
            "end_x": 810,
            "end_y": 450,
            "source": "ai",
            "sentence_index": 2,
            "error_index": 2,
            "comment": "补主语：我",
        },
        {
            "id": "demo_ann_4",
            "type": "star",
            "start_x": 116,
            "start_y": 642,
            "end_x": 116,
            "end_y": 642,
            "source": "ai",
            "sentence_index": 3,
            "error_index": None,
            "comment": "点睛句：全石以为底等重点句理解好",
        },
        {
            "id": "demo_ann_5",
            "type": "wavy",
            "start_x": 120,
            "start_y": 838,
            "end_x": 1180,
            "end_y": 838,
            "source": "ai",
            "sentence_index": 4,
            "error_index": None,
            "comment": "重点句理解非常好",
        },
        {
            "id": "demo_ann_6",
            "type": "line",
            "start_x": 650,
            "start_y": 1218,
            "end_x": 720,
            "end_y": 1218,
            "source": "ai",
            "sentence_index": 5,
            "error_index": 3,
            "comment": "不规范字：藤",
        },
        {
            "id": "demo_ann_7",
            "type": "line",
            "start_x": 910,
            "start_y": 1318,
            "end_x": 1036,
            "end_y": 1318,
            "source": "ai",
            "sentence_index": 5,
            "error_index": 4,
            "comment": "错字：飘拂",
        },
        {
            "id": "demo_ann_8",
            "type": "line",
            "start_x": 836,
            "start_y": 1618,
            "end_x": 966,
            "end_y": 1618,
            "source": "ai",
            "sentence_index": 6,
            "error_index": 5,
            "comment": "错字：俶尔",
        },
    ]

    grading_data = {
        "total_score": 84,
        "total_errors": 6,
        "total_deductions": 16,
        "confidence": "high",
        "overall_comment": "本篇译文整体完成度较高，尤其“全石以为底”等重点句理解较好，能看出对课文大意有把握。主要问题集中在省略主语未补、个别重点词解释不够准确，以及“藤、飘拂、俶尔”等字形错误。订正时要逐字对应原文，不要只写大意。",
        "overall_comment_general": "本篇译文整体完成度较高，尤其“全石以为底”等重点句理解较好，能看出对课文大意有把握。主要问题集中在省略主语未补、个别重点词解释不够准确，以及“藤、飘拂、俶尔”等字形错误。订正时要逐字对应原文，不要只写大意。",
        "overall_comment_encouraging": "这次翻译的重点句掌握不错，特别是小石潭石底形态这一句理解较好。接下来把省略主语补完整，再把几个易错字认真订正，译文会更准确、更像标准答案。",
        "overall_comment_instructive": "文言文翻译必须字字落实。本次仍有省略主语未补、重点词解释不准和错别字问题，尤其“佩环、藤蔓、飘拂、俶尔”要订正到位。建议按原文逐词检查，不要只凭大意翻译。",
        "polished_full_translation": "我从小丘向西走了一百二十步左右，隔着竹林，就能听到水流的声音，好像人身上的玉佩、玉环相碰撞发出的清脆声音，我心里很高兴。于是我砍倒一些竹子，开辟出一条小路，沿着小路往下走，看见了一个小潭。小潭以整块石头为底，靠近岸边，石底有些部分翻卷出来露出水面，形成坻、屿、嵁、岩等各种形态。青翠的树木和翠绿的藤蔓，蒙盖缠绕，摇曳牵连，参差不齐，随风飘拂。",
        "homework_completion": "前半篇完成度较高，重点句大意基本准确，后半篇仍需继续逐词订正。",
        "dimension_scores": {
            "完整度": 18,
            "准确度": 15,
            "重点词掌握": 15,
            "句式处理": 16,
            "表达流畅度": 17,
            "忠实原文": 17,
        },
        "dimension_analysis": {
            "完整度": {"strength": "前半部分翻译较完整。", "weakness": "后半部分仍需继续校对。"},
            "准确度": {"strength": "石底重点句理解较好。", "weakness": "佩环、俶尔等重点词需订正。"},
            "句式处理": {"strength": "部分句子能补出现代语序。", "weakness": "省略主语多处未补。"},
        },
        "strengths": [
            "“全石以为底”相关重点句理解较好。",
            "整体能按原文顺序翻译，前半部分完成度较高。",
        ],
        "weaknesses": [
            "多处省略主语没有补出，现代汉语表达不完整。",
            "个别重点词解释不准确，如“佩环”。",
            "存在错别字或不规范字，如“藤、飘拂、俶尔”。",
        ],
        "suggestions": [
            "逐句对照原文，先补主语，再检查重点词。",
            "把错字整理到订正本，尤其关注藤蔓、飘拂、俶尔。",
            "点睛句可熟读背诵，保持对重点句的准确理解。",
        ],
        "highlight_sentences": [
            "全石以为底，近岸，卷石底以出，为坻，为屿，为嵁，为岩。",
            "日光下澈，影布石上。",
        ],
        "parent_feedback": "孩子对《小石潭记》前半部分理解较好，重点句有亮点。建议家长提醒孩子订正主语、省略句和几个错别字，做到逐字对应原文。",
        "system_tags": ["样式调试", "小石潭记", "老师实批口径"],
        "sentence_analyses": [
            {
                "original_classical": "从小丘西行百二十步，隔篁竹，闻水声，如鸣佩环，心乐之。",
                "student_translation": "沿着小丘向西步行一百二十步左右，隔着竹林就能听到水流的声音，就像人身上的佩环发出的清脆声音，我顿时感到很开心。",
                "standard_translation": "我从小丘向西走一百二十步，隔着竹林，听到水声，好像玉佩玉环相碰撞的声音，心里很高兴。",
                "polished_translation": "我从小丘向西走了一百二十步左右，隔着竹林，就能听到水流的声音，好像身上的玉佩玉环相碰撞发出的清脆声音，我心里很高兴。",
                "sentence_score": 84,
                "is_excellent": False,
                "is_highlight": False,
                "highlight_comment": "",
                "errors": [
                    {
                        "error_type": "主语缺失",
                        "original_text": "沿着小丘向西步行",
                        "correct_text": "我/我们/我和朋友们",
                        "reason": "现代汉语翻译需补出省略主语。",
                        "deduction_points": 2,
                        "bbox": None,
                    },
                    {
                        "error_type": "实词错误",
                        "original_text": "佩环",
                        "correct_text": "腰间的玉佩和玉环相碰撞",
                        "reason": "佩环不是普通装饰，应译出碰撞声。",
                        "deduction_points": 3,
                        "bbox": None,
                    },
                ],
            },
            {
                "original_classical": "全石以为底，近岸，卷石底以出，为坻，为屿，为嵁，为岩。",
                "student_translation": "小水潭的底部是一整块石头，靠近岸边，石头从底部向上卷起，露出水面，形成各种形态。",
                "standard_translation": "小潭以整块石头为底，靠近岸边，石底有些部分翻卷出来露出水面，成为坻、屿、嵁、岩各种形态。",
                "polished_translation": "小潭以整块石头为底，靠近岸边，石底有些部分翻卷出来露出水面，形成坻、屿、嵁、岩等各种形态。",
                "sentence_score": 95,
                "is_excellent": True,
                "is_highlight": True,
                "highlight_comment": "重点句理解非常好",
                "errors": [],
            },
            {
                "original_classical": "青树翠蔓，蒙络摇缀，参差披拂。",
                "student_translation": "树上缠绕着翠绿的藤蔓，互相遮掩，水短参差不齐，随风摆动。",
                "standard_translation": "青葱的树木翠绿的藤蔓，蒙盖缠绕摇曳牵连，参差不齐随风飘拂。",
                "polished_translation": "青葱的树木、翠绿的藤蔓，蒙盖缠绕、摇曳牵连，参差不齐，随风飘拂。",
                "sentence_score": 76,
                "is_excellent": False,
                "is_highlight": False,
                "highlight_comment": "",
                "errors": [
                    {
                        "error_type": "错别字",
                        "original_text": "藤",
                        "correct_text": "藤",
                        "reason": "字形不规范，需要订正。",
                        "deduction_points": 1,
                        "bbox": None,
                    },
                    {
                        "error_type": "错别字",
                        "original_text": "飘拂",
                        "correct_text": "飘拂",
                        "reason": "字形写错，影响重点词落实。",
                        "deduction_points": 1,
                        "bbox": None,
                    }
                ],
            },
        ],
    }

    return {
        "imageB64": image_b64,
        "annotations": annotations,
        "gradingData": grading_data,
        "taskId": "demo_style_debug",
        "fileName": demo_image.name,
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
        sentence_analyses_json = json.dumps([
            {
                "original_classical": sa.original_classical,
                "student_translation": sa.student_translation,
                "standard_translation": sa.standard_translation,
                "polished_translation": sa.polished_translation,
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
        ], ensure_ascii=False)
        
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
            "overall_comment_general": result.overall_comment_general,
            "overall_comment_encouraging": result.overall_comment_encouraging,
            "overall_comment_instructive": result.overall_comment_instructive,
            "polished_full_translation": result.polished_full_translation,
            "recognized_text": result.recognized_text,
            "homework_completion": result.homework_completion,
            "dimension_scores": result.dimension_scores,
            "dimension_analysis": getattr(result, 'dimension_analysis', {}),
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
                    "polished_translation": sa.polished_translation,
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
                sentence_analyses_json=sentence_analyses_json,
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
                "overall_comment_general": result.overall_comment_general,
                "overall_comment_encouraging": result.overall_comment_encouraging,
                "overall_comment_instructive": result.overall_comment_instructive,
                "polished_full_translation": result.polished_full_translation,
                "homework_completion": result.homework_completion,
                "dimension_scores": result.dimension_scores,
                "dimension_analysis": getattr(result, 'dimension_analysis', {}),
                "strengths": result.strengths,
                "weaknesses": result.weaknesses,
                "suggestions": result.suggestions,
                "highlight_sentences": result.highlight_sentences,
                "parent_feedback": result.parent_feedback,
                "system_tags": result.system_tags,
                "sentence_analyses": [
                    {
                        "original_classical": sa.original_classical,
                        "student_translation": sa.student_translation,
                        "standard_translation": sa.standard_translation,
                        "polished_translation": sa.polished_translation,
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
                ]
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
    """保存标注数据和可选的批改报告数据"""
    data = request.get_json()
    if not data:
        return {"error": "缺少数据"}, 400
    
    if "annotations" in data:
        _annotation_store[task_id] = data["annotations"]
        print(f"[DEBUG] 保存标注: task={task_id}, count={len(data['annotations'])}")
        
    # 如果有 gradingData，同时将其保存到对应的 JSON 报告文件中
    if "gradingData" in data and "fileName" in data:
        fileName = data["fileName"]
        gradingData = data["gradingData"]
        
        # 重新组合完整的 JSON 报告结构
        report_data = {
            "grader": gradingData.get("grader_name", "fusion"),
            "total_score": gradingData.get("total_score", 0),
            "total_errors": gradingData.get("total_errors", 0),
            "total_deductions": gradingData.get("total_deductions", 0),
            "confidence": gradingData.get("confidence", "中"),
            "status": "success",
            "processing_time_ms": gradingData.get("processing_time_ms", 0),
            "overall_comment": gradingData.get("overall_comment", ""),
            "overall_comment_general": gradingData.get("overall_comment_general", ""),
            "overall_comment_encouraging": gradingData.get("overall_comment_encouraging", ""),
            "overall_comment_instructive": gradingData.get("overall_comment_instructive", ""),
            "polished_full_translation": gradingData.get("polished_full_translation", ""),
            "recognized_text": gradingData.get("recognized_text", ""),
            "homework_completion": gradingData.get("homework_completion", ""),
            "dimension_scores": gradingData.get("dimension_scores", {}),
            "dimension_analysis": gradingData.get("dimension_analysis", {}),
            "strengths": gradingData.get("strengths", []),
            "weaknesses": gradingData.get("weaknesses", []),
            "suggestions": gradingData.get("suggestions", []),
            "highlight_sentences": gradingData.get("highlight_sentences", []),
            "parent_feedback": gradingData.get("parent_feedback", ""),
            "system_tags": gradingData.get("system_tags", []),
            "annotations": data.get("annotations", []),
            "sentence_analyses": gradingData.get("sentence_analyses", [])
        }
        
        try:
            upload_dir = PROJECT_ROOT / "output" / "uploads"
            base_name = fileName.replace(".jpg", "").replace(".png", "").replace(".jpeg", "")
            report_path = upload_dir / f"graded_{base_name}_report.json"
            
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
            print(f"[DEBUG] 成功更新本地报告文件: {report_path}")
        except Exception as e:
            print(f"[ERROR] 保存报告文件失败: {e}")
            
    return {"ok": True, "count": len(data.get("annotations", []))}


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
    port = int(os.environ.get("PORT", "8080"))
    print("=" * 50)
    print("🚀 AI 批改 PoC Web 服务启动")
    print("=" * 50)
    print(f"访问地址: http://localhost:{port}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
