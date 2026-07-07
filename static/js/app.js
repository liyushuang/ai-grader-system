/**
 * 应用入口 — 标注编辑器主逻辑
 * 负责：初始化、上传处理、工具栏操作、保存/导出
 */

// ═══════════════════════════════════════════════
// 工具栏
// ═══════════════════════════════════════════════

function setTool(tool) {
    currentTool = tool;
    
    // 更新工具栏按钮状态
    ['toolSelect', 'toolWavy', 'toolLine', 'toolCircle'].forEach(id => {
        document.getElementById(id)?.classList.remove('active');
    });
    
    const btnMap = { select: 'toolSelect', wavy: 'toolWavy', line: 'toolLine', circle: 'toolCircle' };
    if (btnMap[tool]) {
        document.getElementById(btnMap[tool]).classList.add('active');
    }

    // 更新光标样式
    if (window.canvasManager && window.canvasManager.fabric) {
        const fc = window.canvasManager.fabric;
        if (tool === 'select') {
            fc.defaultCursor = 'default';
            fc.selection = false;
            fc.getObjects().forEach(o => { if (o.annotationType) o.selectable = true; });
        } else {
            fc.defaultCursor = 'crosshair';
            fc.selection = false;
            fc.discardActiveObject();
            fc.getObjects().forEach(o => { if (o.annotationType) o.selectable = false; });
        }
        fc.renderAll();
    }
}

// ═══════════════════════════════════════════════
// 标注操作
// ═══════════════════════════════════════════════

function deleteSelected() {
    const sel = window.annotationStore.getSelected();
    if (!sel) {
        showToast('请先选中一个标注');
        return;
    }

    if (sel.source === 'ai' && !confirm('这是AI生成的标注，确定要删除吗？')) return;

    const annId = sel.id;
    const backup = { ...sel };

    window.annotationStore.remove(annId);
    window.canvasManager.removeAnnotation(annId);

    window.undoManager.execute({
        type: 'delete',
        annotationId: annId,
        previousState: backup,
        execute: () => {},
        undo: () => {
            window.annotationStore.add(backup);
            window.canvasManager.addAnnotation(backup);
        },
    });

    showToast('已删除标注');
}

function deleteAnnotation(annId) {
    window.annotationStore.select(annId);
    deleteSelected();
}

function contextSwitchType(newType) {
    const menu = document.getElementById('contextMenu');
    const annId = menu._annId;
    menu.style.display = 'none';

    if (!annId) return;
    switchAnnotationType(annId, newType);
}

function switchAnnotationType(annId, newType) {
    const ann = window.annotationStore.getById(annId);
    if (!ann) return;

    const oldType = ann.type;
    window.annotationStore.update(annId, { type: newType, source: 'teacher' });
    window.canvasManager.updateAnnotationStyle(ann);

    window.undoManager.execute({
        type: 'modify',
        annotationId: annId,
        previousState: { type: oldType },
        newState: { type: newType },
        execute: () => {},
        undo: () => {
            window.annotationStore.update(annId, { type: oldType });
            window.canvasManager.updateAnnotationStyle(window.annotationStore.getById(annId));
        },
    });

    showToast('标注类型已切换');
}

// ═══════════════════════════════════════════════
// 编辑面板
// ═══════════════════════════════════════════════

function onEditTypeChange() {
    const newType = document.getElementById('editType').value;
    const sel = window.annotationStore.getSelected();
    if (sel && sel.type !== newType) {
        switchAnnotationType(sel.id, newType);
    }
}

function saveEdit() {
    const sel = window.annotationStore.getSelected();
    if (!sel) return;

    const comment = document.getElementById('editComment').value;
    const type = document.getElementById('editType').value;
    const oldComment = sel.comment;
    const oldType = sel.type;

    window.annotationStore.update(sel.id, { comment, type });

    if (type !== oldType) {
        window.canvasManager.updateAnnotationStyle(sel);
    }

    window.undoManager.execute({
        type: 'modify',
        annotationId: sel.id,
        previousState: { comment: oldComment, type: oldType },
        newState: { comment, type },
        execute: () => {},
        undo: () => {
            window.annotationStore.update(sel.id, { comment: oldComment, type: oldType });
            if (type !== oldType) window.canvasManager.updateAnnotationStyle(window.annotationStore.getById(sel.id));
        },
    });

    showToast('批注已保存');
}

function cancelEdit() {
    const sel = window.annotationStore.getSelected();
    if (sel) {
        document.getElementById('editType').value = sel.type;
        document.getElementById('editComment').value = sel.comment || '';
    }
    document.getElementById('editModal')?.classList.remove('active');
}

// ═══════════════════════════════════════════════
// 撤销/重做
// ═══════════════════════════════════════════════

function undo() {
    const cmd = window.undoManager.undo();
    if (cmd) showToast('已撤销');
}

function redo() {
    const cmd = window.undoManager.redo();
    if (cmd) showToast('已重做');
}

// ═══════════════════════════════════════════════
// 保存 & 导出
// ═══════════════════════════════════════════════

async function saveAnnotations() {
    const session = imageSessions[currentImageIndex];
    const tid = session ? session.taskId : ('task_' + Date.now());
    if (!tid) {
        taskId = 'task_' + Date.now();
    } else {
        taskId = tid;
    }

    const data = window.annotationStore.toJSON();
    // 同步回session
    if (session) {
        session.annotations = data;
    }
    try {
        const resp = await fetch('/api/annotations/' + taskId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ annotations: data }),
        });
        const result = await resp.json();
        if (result.ok) {
            showToast('✅ 标注已保存 (' + result.count + ' 个)');
        }
    } catch (e) {
        showToast('❌ 保存失败: ' + e.message);
    }
}

function exportImage() {
    if (!window.canvasManager.fabric) {
        showToast('请先批改一张图片');
        return;
    }

    const dataUrl = window.canvasManager.exportImage('png');
    const link = document.createElement('a');
    link.download = 'annotated_homework.png';
    link.href = dataUrl;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('✅ 图片已导出');
}

/** 清空所有标注 */
function clearAllAnnotations() {
    if (!window.annotationStore || window.annotationStore.count === 0) return;
    if (!confirm(`确定要清空全部 ${window.annotationStore.count} 个标注吗？此操作可撤销。`)) return;

    const backup = window.annotationStore.getAll().map(a => ({...a}));
    const ids = backup.map(a => a.id);

    ids.forEach(id => {
        window.annotationStore.remove(id);
        window.canvasManager.removeAnnotation(id);
    });

    window.undoManager.execute({
        type: 'clearAll',
        annotationId: 'all',
        previousState: { annotations: backup },
        execute: () => {},
        undo: () => {
            backup.forEach(a => {
                window.annotationStore.add(a);
                window.canvasManager.addAnnotation(a);
            });
        },
    });

    showToast('已清空全部标注');
}

/** 重置为AI标注 */
function resetToAI() {
    if (!window.__gradingData || !window.__gradingData.annotations) {
        showToast('无AI标注数据可恢复');
        return;
    }
    if (!confirm('确定要重置为AI原始标注吗？当前所有手动修改将丢失。')) return;

    window.annotationStore.annotations = [];
    window.annotationStore.selectedId = null;

    // 清除Canvas上旧标注
    if (window.canvasManager.fabric) {
        window.canvasManager.fabric.getObjects().forEach(obj => {
            if (obj.annotationType) window.canvasManager.fabric.remove(obj);
        });
    }

    // 重新加载
    window.annotationStore.load(window.__gradingData.annotations);
    window.canvasManager.renderAnnotations(window.annotationStore.getAll());
    window.sidePanel.renderList(window.annotationStore.getAll());
    window.undoManager.clear();

    showToast('✅ 已重置为AI标注');
}

function resetAll() {
    if (window.annotationStore.count > 0 && !confirm('当前标注未保存，确定要重新上传吗？')) return;

    // 清理状态
    window.annotationStore.annotations = [];
    window.annotationStore.selectedId = null;
    window.undoManager.clear();
    taskId = null;
    currentTool = 'select';

    // 显示上传界面
    document.getElementById('uploadOverlay').classList.add('show');
    
    // 清理Canvas
    if (window.canvasManager.fabric) {
        window.canvasManager.fabric.clear();
        window.canvasManager.fabric.backgroundImage = null;
        window.canvasManager.fabric.renderAll();
    }

    setTool('select');
    document.getElementById('mainLayout')?.classList.add('empty');
    if (window.sidePanel) window.sidePanel.clearAllViews();
    document.getElementById('editModal')?.classList.remove('active');
};

// ═══════════════════════════════════════════════
// 多图管理
// ═══════════════════════════════════════════════
let imageSessions = {};  // { index: { imageB64, annotations, gradingData, taskId } }
let currentImageIndex = -1;
let aiOriginalAnnotations = null;  // 当前图片的AI原始标注备份
let llmOutputBuffer = '';  // LLM流式输出缓冲
let stageLogBuffer = '';  // 阶段进度日志缓冲
let gradingFailures = [];  // 批改失败原因

function isFusionPipeline(grader) {
    return grader === 'fusion' || grader === 'ark_code';
}

function getGraderDisplayName(grader) {
    const names = {
        fusion: '千问 qwen3.6-max-preview 无思考',
        ark_code: '方舟 ark-code-latest',
    };
    return names[grader] || grader || '未知模型';
}

function handleFileSelect(input) {
    if (!input.files || input.files.length === 0) return;
    
    const files = Array.from(input.files);
    const grader = document.querySelector('input[name="grader"]:checked')?.value || 'fusion';
    gradingFailures = [];
    
    document.getElementById('uploadOverlay').classList.remove('show');
    document.getElementById('mainLayout')?.classList.add('empty');
    if (window.sidePanel) window.sidePanel.clearAllViews();
    // 融合批改用 thinking panel 展示进度，不需要 loading overlay
    if (!isFusionPipeline(grader)) {
        document.getElementById('loadingOverlay').classList.add('show');
    }
    
    // 显示思考过程面板（融合方案专属，内联展示）
    const thinkingPanel = document.getElementById('thinkingPanel');
    const thinkingStages = document.getElementById('thinkingStages');
    const thinkingOutput = document.getElementById('thinkingOutput');
    const thinkingProgress = document.getElementById('thinkingProgress');
    const thinkingDoneBadge = document.getElementById('thinkingDoneBadge');
    const thinkingHeaderText = document.querySelector('#thinkingPanel .header-text');
    if (isFusionPipeline(grader)) {
        thinkingPanel.classList.add('show');
        thinkingPanel.classList.remove('collapsed');
        if (thinkingHeaderText) {
            thinkingHeaderText.textContent = `AI 批改思考过程 · ${getGraderDisplayName(grader)}`;
        }
        // 重置阶段标签状态（预渲染的标签只改样式，不重建DOM）
        const stageIcons = { ocr: '🔍', clean: '🧹', align: '🧭', rule: '📐', llm: '🧠', fuse: '🔗' };
        document.querySelectorAll('.thinking-stage').forEach(el => {
            el.classList.remove('active', 'done');
            const icon = el.querySelector('.stage-icon');
            const sid = (el.id || '').replace('stage-', '');
            if (icon) { icon.classList.remove('spin'); icon.textContent = stageIcons[sid] || icon.textContent; }
        });
        thinkingOutput.textContent = '';
        thinkingProgress.style.width = '0%';
        thinkingDoneBadge.classList.remove('show');
        llmOutputBuffer = '';
        stageLogBuffer = `<div class="llm-status">• 当前模型：${escapeHtml(getGraderDisplayName(grader))}</div>`;
        thinkingOutput.innerHTML = stageLogBuffer;
    }
    
    // 逐个批改
    let completed = 0;
    const total = files.length;
    
    files.forEach((file, idx) => {
        const formData = new FormData();
        formData.append('image', file);
        formData.append('grader', grader);
        
        // 融合方案用流式接口，其他用普通接口
        if (isFusionPipeline(grader)) {
            streamGrade(file, idx, grader, () => {
                completed++;
                onAllComplete(completed, total);
            });
        } else {
            fetch('/grade_json?t=' + Date.now(), { method: 'POST', body: formData, cache: 'no-store' })
                .then(resp => resp.json())
                .then(data => {
                    completed++;
                    if (data.ok) {
                        imageSessions[idx] = buildSession(data, file, idx);
                    }
                    onAllComplete(completed, total);
                })
                .catch(err => {
                    completed++;
                    console.error(`图片${idx+1}批改失败:`, err);
                    onAllComplete(completed, total);
                });
        }
    });
}

async function streamGrade(file, idx, grader, onDone) {
    const formData = new FormData();
    formData.append('image', file);
    formData.append('grader', grader);
    
    const thinkingStages = document.getElementById('thinkingStages');
    const thinkingOutput = document.getElementById('thinkingOutput');
    const thinkingPanel = document.getElementById('thinkingPanel');
    const thinkingProgress = document.getElementById('thinkingProgress');
    const thinkingDoneBadge = document.getElementById('thinkingDoneBadge');
    
    try {
        const response = await fetch('/grade_stream?t=' + Date.now(), { method: 'POST', body: formData, cache: 'no-store' });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            
            // 解析 SSE 事件
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6));
                        handleStreamEvent(event, thinkingStages, thinkingOutput, thinkingProgress, thinkingDoneBadge);
                        
                        // 收到最终结果
                        if (event.type === 'result') {
                            const imgData = await loadImageAsBase64(file);
                            imageSessions[idx] = {
                                imageB64: imgData,
                                annotations: event.data.annotations,
                                gradingData: normalizeGradingData(event.data, event.data.annotations),
                                taskId: 'task_' + Date.now() + '_' + idx,
                                fileName: file.name,
                            };
                            // 延迟关闭思考面板
                            setTimeout(() => {
                                thinkingPanel.classList.remove('show');
                            }, 2000);
                            onDone();
                        }
                        
                        if (event.type === 'error') {
                            const message = event.message || '批改失败';
                            gradingFailures.push(`${file.name}: ${message}`);
                            showToast('❌ ' + message);
                            thinkingPanel.classList.remove('show');
                            onDone();
                        }
                    } catch (e) {
                        // 忽略解析错误
                    }
                }
            }
        }
    } catch (err) {
        console.error(`图片${idx+1}流式批改失败:`, err);
        gradingFailures.push(`${file.name}: ${err.message || err}`);
        thinkingPanel.classList.remove('show');
        onDone();
    }
}

// 阶段顺序
const STAGE_ORDER = ['ocr', 'clean', 'align', 'rule', 'llm', 'fuse'];
const STAGE_PROGRESS = {
    ocr: 12, clean: 26, align: 42, rule: 58, llm: 78, fuse: 92, done: 100,
    ocr_done: 20, clean_done: 34, align_done: 50, rule_done: 66,
    llm_done: 86, llm_timeout: 86, fuse_done: 100,
};
const STAGE_LABELS = {
    ocr: 'OCR识别', clean: '文本清洗', align: '标准对齐',
    rule: '规则初判', llm: '模型复核', fuse: '坐标回填',
};

function normalizeStageId(stage) {
    if (!stage) return '';
    if (stage.endsWith('_done')) return stage.replace('_done', '');
    if (stage === 'llm_timeout') return 'llm';
    return stage;
}

function handleStreamEvent(event, thinkingStages, thinkingOutput, thinkingProgress, thinkingDoneBadge) {
    if (event.type === 'result') {
        thinkingProgress.style.width = '100%';
        thinkingDoneBadge.classList.add('show');
        STAGE_ORDER.forEach((sid) => {
            const el = document.getElementById('stage-' + sid);
            if (!el) return;
            const iconEl = el.querySelector('.stage-icon');
            el.classList.remove('active');
            el.classList.add('done');
            if (iconEl) {
                iconEl.classList.remove('spin');
                iconEl.textContent = '✅';
            }
        });
        return;
    }

    if (event.type === 'stage') {
        // 进度条更新
        if (STAGE_PROGRESS[event.stage]) {
            thinkingProgress.style.width = STAGE_PROGRESS[event.stage] + '%';
        }
        if (event.stage === 'done' || event.stage === 'fuse_done') {
            thinkingProgress.style.width = '100%';
            thinkingDoneBadge.classList.add('show');
        }
        
        // 更新阶段标签（标签已预渲染，只改样式，不创建DOM）
        const baseStage = normalizeStageId(event.stage);
        const currentIdx = STAGE_ORDER.indexOf(baseStage);
        const isDoneEvent = event.stage.endsWith('_done') || event.stage === 'llm_timeout';
        STAGE_ORDER.forEach((sid, i) => {
            const el = document.getElementById('stage-' + sid);
            if (!el) return;
            const iconEl = el.querySelector('.stage-icon');
            el.classList.remove('active', 'done');
            iconEl.classList.remove('spin');
            
            if (i < currentIdx || (i === currentIdx && isDoneEvent)) {
                // 已完成
                el.classList.add('done');
                iconEl.textContent = '✅';
            } else if (i === currentIdx) {
                // 进行中
                el.classList.add('active');
                iconEl.classList.add('spin');
            }
            // 其他保持默认（灰色待处理）
        });

        if (event.message) {
            const label = STAGE_LABELS[baseStage] || '阶段进度';
            const prefix = event.stage.endsWith('_done') ? '✓' : (event.stage === 'llm_timeout' ? '!' : '•');
            const line = `<div class="llm-status">${prefix} ${label}：${escapeHtml(event.message)}</div>`;
            stageLogBuffer += line;
            thinkingOutput.innerHTML = stageLogBuffer + extractReadableContent(llmOutputBuffer) + '<span class="cursor-blink"></span>';
            thinkingOutput.scrollTop = thinkingOutput.scrollHeight;
        }
    }
    
    if (event.type === 'llm_chunk') {
        llmOutputBuffer += event.text;
        const display = stageLogBuffer + extractReadableContent(llmOutputBuffer);
        thinkingOutput.innerHTML = display + '<span class="cursor-blink"></span>';
        thinkingOutput.scrollTop = thinkingOutput.scrollHeight;
    }
}

function escapeHtml(text) {
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * 从 LLM 原始 JSON 输出中提取可读内容
 * 只展示当前正在分析的句子关键信息
 */
function extractReadableContent(rawText) {
    // 尝试提取当前句子分析
    const sentences = [];
    
    // 匹配 "original_classical": "..." 和 "student_translation": "..."
    const classicalMatches = rawText.match(/"original_classical"\s*:\s*"([^"]+)"/g);
    const studentMatches = rawText.match(/"student_translation"\s*:\s*"([^"]+)"/g);
    const errorMatches = rawText.match(/"error_type"\s*:\s*"([^"]+)"/g);
    const reasonMatches = rawText.match(/"reason"\s*:\s*"([^"]+)"/g);
    
    if (classicalMatches && studentMatches) {
        // 取最后一对（当前正在分析的句子）
        const lastClassical = classicalMatches[classicalMatches.length - 1];
        const lastStudent = studentMatches[studentMatches.length - 1];
        const classical = lastClassical.match(/"([^"]+)"$/)[1];
        const student = lastStudent.match(/"([^"]+)"$/)[1];
        
        let html = `<div class="llm-sentence">`;
        html += `<div class="llm-line"><span class="llm-label">原文</span>${classical}</div>`;
        html += `<div class="llm-line"><span class="llm-label">译文</span>${student}</div>`;
        
        // 如果有错误，显示错误信息
        if (errorMatches && errorMatches.length > 0) {
            const lastError = errorMatches[errorMatches.length - 1];
            const errorType = lastError.match(/"([^"]+)"$/)[1];
            html += `<div class="llm-line"><span class="llm-label error">问题</span>${errorType}`;
            if (reasonMatches && reasonMatches.length > 0) {
                const lastReason = reasonMatches[reasonMatches.length - 1];
                const reason = lastReason.match(/"([^"]+)"$/)[1];
                html += ` — ${reason}`;
            }
            html += `</div>`;
        }
        html += `</div>`;
        return html;
    }
    
    // 如果还没解析到句子，显示简化状态
    if (rawText.includes('sentence_analysis')) {
        return '<div class="llm-status">📖 正在逐句分析中...</div>';
    }
    if (rawText.includes('dimension_scores')) {
        return '<div class="llm-status">📊 正在生成评分报告...</div>';
    }
    if (rawText.includes('overall_comment')) {
        return '<div class="llm-status">💬 正在撰写教师评语...</div>';
    }
    
    // 完全无法解析时，显示截断的原始文本（但美化）
    const truncated = rawText.length > 500 ? '...' + rawText.slice(-500) : rawText;
    return '<div class="llm-status">🤖 AI 正在思考...</div>';
}

// 折叠/展开思考面板
function toggleThinkingPanel() {
    document.getElementById('thinkingPanel').classList.toggle('collapsed');
}

function loadImageAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

function normalizeGradingData(raw, annotations = []) {
    const d = raw || {};
    const correctionComments = (annotations || [])
        .filter(a => ['line', 'circle'].includes(a.type))
        .map(a => a.comment)
        .filter(Boolean);
    const score = Number.isFinite(Number(d.total_score)) ? Number(d.total_score) : 0;
    return {
        total_score: score,
        total_errors: d.total_errors ?? correctionComments.length,
        total_deductions: d.total_deductions ?? 0,
        confidence: d.confidence || '中',
        overall_comment: d.overall_comment || d.overall_comment_general || '本次批改已生成标注，请结合图片中的标注逐项订正。',
        overall_comment_general: d.overall_comment_general || d.overall_comment || '本次批改已生成标注，请结合图片中的标注逐项订正。',
        overall_comment_encouraging: d.overall_comment_encouraging || '',
        overall_comment_instructive: d.overall_comment_instructive || '',
        polished_full_translation: d.polished_full_translation || '',
        homework_completion: d.homework_completion || '',
        dimension_scores: d.dimension_scores || {},
        dimension_analysis: d.dimension_analysis || {},
        strengths: Array.isArray(d.strengths) ? d.strengths : [],
        weaknesses: Array.isArray(d.weaknesses) ? d.weaknesses : correctionComments,
        suggestions: Array.isArray(d.suggestions) ? d.suggestions : [],
        highlight_sentences: Array.isArray(d.highlight_sentences) ? d.highlight_sentences : [],
        parent_feedback: d.parent_feedback || '',
        system_tags: Array.isArray(d.system_tags) ? d.system_tags : [],
        sentence_analyses: Array.isArray(d.sentence_analyses) ? d.sentence_analyses : [],
        grader_name: d.grader_name || 'fusion',
        processing_time_ms: d.processing_time_ms || 0,
        annotations: annotations || d.annotations || [],
    };
}

function buildSession(data, file, idx) {
    const result = data.grading_result || {};
    return {
        imageB64: data.image_b64,
        annotations: data.annotations,
        gradingData: normalizeGradingData({
            total_score: result.total_score,
            total_errors: result.total_errors,
            total_deductions: result.total_deductions,
            confidence: result.confidence,
            overall_comment: result.overall_comment,
            overall_comment_general: result.overall_comment_general,
            overall_comment_encouraging: result.overall_comment_encouraging,
            overall_comment_instructive: result.overall_comment_instructive,
            polished_full_translation: result.polished_full_translation,
            homework_completion: result.homework_completion,
            dimension_scores: result.dimension_scores,
            dimension_analysis: result.dimension_analysis,
            strengths: result.strengths,
            weaknesses: result.weaknesses,
            suggestions: result.suggestions,
            highlight_sentences: result.highlight_sentences,
            parent_feedback: result.parent_feedback,
            system_tags: result.system_tags,
            sentence_analyses: result.sentence_analyses,
            grader_name: result.grader_name,
            processing_time_ms: result.processing_time_ms,
        }, data.annotations),
        taskId: 'task_' + Date.now() + '_' + idx,
        fileName: file.name,
    };
}

function loadDemoSession() {
    if (!window.__demoSession) return;

    document.getElementById('uploadOverlay').classList.remove('show');
    document.getElementById('loadingOverlay').classList.remove('show');
    document.getElementById('thinkingPanel').classList.remove('show');
    document.getElementById('mainLayout').classList.remove('empty');

    imageSessions = {
        0: {
            imageB64: window.__demoSession.imageB64,
            annotations: window.__demoSession.annotations || [],
            gradingData: normalizeGradingData(window.__demoSession.gradingData || {}, window.__demoSession.annotations || []),
            taskId: window.__demoSession.taskId || 'demo_style_debug',
            fileName: window.__demoSession.fileName || '样式调试样例',
        }
    };
    currentImageIndex = -1;
    aiOriginalAnnotations = JSON.parse(JSON.stringify(imageSessions[0].annotations));
    switchToImage(0);
    renderImageTabs();
    showToast('已加载样式调试样例');
}

function onAllComplete(completed, total) {
    document.getElementById('loadingOverlay').classList.remove('show');
    if (Object.keys(imageSessions).length > 0) {
        switchToImage(0);
        renderImageTabs();
        showToast(`✅ 已批改 ${completed}/${total} 张图片`);
    } else {
        document.getElementById('uploadOverlay').classList.add('show');
        document.getElementById('mainLayout')?.classList.add('empty');
        if (window.sidePanel) window.sidePanel.clearAllViews();
        const reason = gradingFailures.length ? gradingFailures[0] : '所有图片批改失败';
        showToast('❌ ' + reason);
    }
}

function renderImageTabs() {
    const tabs = document.getElementById('imageTabs');
    tabs.style.display = 'flex';
    tabs.innerHTML = '';
    
    Object.keys(imageSessions).sort().forEach(idx => {
        const s = imageSessions[idx];
        const tab = document.createElement('span');
        tab.className = 'img-tab' + (parseInt(idx) === currentImageIndex ? ' active' : '');
        tab.textContent = `📄 ${s.fileName || ('图' + (parseInt(idx)+1))}`;
        tab.onclick = () => switchToImage(parseInt(idx));
        tabs.appendChild(tab);
    });
}

function switchToImage(index) {
    if (!imageSessions[index]) return;
    
    // 保存当前图片的标注
    if (currentImageIndex >= 0 && imageSessions[currentImageIndex]) {
        imageSessions[currentImageIndex].annotations = window.annotationStore.toJSON();
    }
    
    currentImageIndex = index;
    const session = imageSessions[index];
    document.getElementById('mainLayout').classList.remove('empty');
    
    // 重置状态
    window.annotationStore.annotations = [];
    window.annotationStore.selectedId = null;
    window.undoManager.clear();
    aiOriginalAnnotations = JSON.parse(JSON.stringify(session.annotations));
    
    // 重新初始化Canvas
    if (!window.canvasManager.fabric) {
        window.canvasManager.init();
    }
    
    window.canvasManager.loadImage(session.imageB64).then(() => {
        // 加载标注
        window.annotationStore.load(session.annotations);
        window.canvasManager.renderAnnotations(window.annotationStore.getAll());
        window.sidePanel.renderList(window.annotationStore.getAll());
        window.undoManager.clear();
        
        // 绑定 Fabric 的重绘事件以自动计算旁批位置
        if (window.canvasManager.fabric) {
            window.canvasManager.fabric.off('after:render');
            window.canvasManager.fabric.on('after:render', () => {
                if (window.sidePanel && typeof window.sidePanel.layoutSideBySideCards === 'function') {
                    window.sidePanel.layoutSideBySideCards();
                }
            });
        }
        
        // 加载批改报告
        session.gradingData = normalizeGradingData(session.gradingData, session.annotations);
        window.sidePanel.loadGradingData(session.gradingData);
        
        renderImageTabs();
        setTool('select');
        showToast(`已切换到: ${session.fileName || ('图' + (index+1))}`);
    }).catch(err => {
        console.error('切换图片失败:', err);
        showToast('❌ 图片加载失败');
    });
}

/** 覆盖 resetToAI：重置当前图片 */
resetToAI = function() {
    if (!aiOriginalAnnotations || aiOriginalAnnotations.length === 0) {
        showToast('无AI标注数据可恢复');
        return;
    }
    if (!confirm('确定要重置为AI原始标注吗？当前所有手动修改将丢失。')) return;
    
    window.annotationStore.annotations = [];
    window.annotationStore.selectedId = null;
    
    if (window.canvasManager.fabric) {
        window.canvasManager.fabric.getObjects().forEach(obj => {
            if (obj.annotationType) window.canvasManager.fabric.remove(obj);
        });
    }
    
    window.annotationStore.load(aiOriginalAnnotations);
    window.canvasManager.renderAnnotations(window.annotationStore.getAll());
    window.sidePanel.renderList(window.annotationStore.getAll());
    window.undoManager.clear();
    
    showToast('✅ 已重置为AI标注');
};

/** 覆盖 resetAll */
resetAll = function() {
    imageSessions = {};
    gradingFailures = [];
    currentImageIndex = -1;
    aiOriginalAnnotations = null;
    window.annotationStore.annotations = [];
    window.annotationStore.selectedId = null;
    window.undoManager.clear();
    taskId = null;
    currentTool = 'select';
    
    document.getElementById('uploadOverlay').classList.add('show');
    document.getElementById('mainLayout').classList.add('empty');
    document.getElementById('imageTabs').style.display = 'none';
    document.getElementById('imageTabs').innerHTML = '';
    
    if (window.canvasManager.fabric) {
        window.canvasManager.fabric.clear();
        window.canvasManager.fabric.backgroundImage = null;
        window.canvasManager.fabric.renderAll();
    }
    
    setTool('select');
    if (window.sidePanel) window.sidePanel.clearAllViews();
    document.getElementById('editModal').classList.remove('active');
};

// ═══════════════════════════════════════════════
// Toast
// ═══════════════════════════════════════════════

function showToast(msg) {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => {
        toast.classList.remove('show');
    }, 2000);
}

// ═══════════════════════════════════════════════
// 页面启动
// ═══════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('fileInput');
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            handleFileSelect(this);
        });
    }
    
    // 初始化侧边面板
    if (window.sidePanel) window.sidePanel.init();
    if (window.__pageMode === 'demo') loadDemoSession();
    
    // 默认选中融合批改
    const fusionRadio = document.getElementById('graderFusion');
    if (fusionRadio) fusionRadio.checked = true;
});
