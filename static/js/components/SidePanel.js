/**
 * 侧边面板组件 — 支持标注列表 + 批改报告 Tab 切换
 * 管理标注列表渲染、编辑面板交互、批改报告展示
 */
class SidePanel {
    constructor() {
        this.listEl = document.getElementById('annotationList');
        this.editPanel = document.getElementById('editPanel');
        this.editModal = document.getElementById('editModal');
        this.editType = document.getElementById('editType');
        this.editComment = document.getElementById('editComment');
        this.panelCount = document.getElementById('panelCount');
        this._editingId = null;
        this._currentTab = 'report';
        this.reportPanel = null;
        this.gradingData = null;
    }

    init() {
        window.annotationStore.onChange((annotations) => {
            this.renderList(annotations);
            this.renderSideBySide(annotations);
            this.refreshEditPanel();
        });
        window.annotationStore.onSelect((ann) => {
            this.showEdit(ann);
            this.updateSideCardSelection(ann ? ann.id : null);
        });

        // 初始化批改报告面板
        this.reportPanel = new GradingReportPanel('gradingReport');

        // 窗口大小变化重新排列旁批
        window.addEventListener('resize', () => {
            this.layoutSideBySideCards();
        });
    }

    switchTab(tab) {
        this._currentTab = 'report';
        document.getElementById('panelReport').style.display = 'flex';
        requestAnimationFrame(() => this.layoutSideBySideCards());
    }

    openAnnotationEditor(annId) {
        const ann = window.annotationStore.getById(annId);
        if (!ann) return;

        window.annotationStore.select(annId);
        window.canvasManager.selectAnnotation(annId);
        this.showEdit(ann);

        requestAnimationFrame(() => {
            this.editComment.focus();
            this.editComment.select();
        });
    }

    /**
     * 加载批改数据并渲染报告
     */
    loadGradingData(gradingData) {
        this.gradingData = gradingData || null;
        if (this.reportPanel && gradingData) {
            this.reportPanel.render(gradingData);
        }
        if (window.annotationStore) {
            this.renderSideBySide(window.annotationStore.getAll());
        }
    }

    clearAllViews() {
        this.renderSideBySide([]);
        this.gradingData = null;
        this.showEdit(null);
        if (this.reportPanel) this.reportPanel.clear();
    }

    /**
     * 渲染标注列表
     */
    renderList(annotations) {
        if (!this.listEl || !this.panelCount) return;
        this.listEl.innerHTML = '';
        this.panelCount.textContent = annotations.length + ' 个';

        if (annotations.length === 0) {
            this.listEl.innerHTML = '<div style="padding:20px;text-align:center;color:#bbb;font-size:13px;">暂无标注</div>';
            return;
        }

        annotations.forEach((ann, idx) => {
            const item = document.createElement('div');
            item.className = 'ann-item' + (ann.id === window.annotationStore.selectedId ? ' selected' : '');
            item.onclick = () => this._onItemClick(ann.id);

            const iconMap = { wavy: ['∼', 'wavy'], line: ['—', 'line'], circle: ['○', 'circle'], star: ['∼', 'wavy'], check: ['✓', 'check'] };
            const [icon, cls] = iconMap[ann.type] || ['?', 'line'];
            const typeLabelMap = { wavy: '点睛句', line: '横线·纠错', circle: '圆圈·错字', star: '点睛句', check: '对勾·翻译正确' };
            const typeLabel = typeLabelMap[ann.type] || ann.type;
            const sourceLabel = ann.source === 'ai' ? '🤖 AI' : '👤 教师';

            item.innerHTML = `
                <div class="ann-icon ${cls}">${icon}</div>
                <div class="ann-content">
                    <div class="ann-type-label ${cls}">${typeLabel}</div>
                    <div class="ann-comment">${this._escapeHtml(ann.comment || '(无批注)')}</div>
                    <div class="ann-source">${sourceLabel}</div>
                </div>
                <button class="ann-delete" onclick="event.stopPropagation();deleteAnnotation('${ann.id}')" title="删除">×</button>
            `;

            this.listEl.appendChild(item);
        });
    }

    /**
     * 显示编辑面板
     */
    showEdit(ann) {
        if (!ann) {
            this.editModal.classList.remove('active');
            this._editingId = null;
            return;
        }

        this._editingId = ann.id;
        this.editType.value = ann.type;
        this.editComment.value = ann.comment || '';
        this.editModal.classList.add('active');
    }

    refreshEditPanel() {
        if (!this._editingId) return;
        const ann = window.annotationStore.getById(this._editingId);
        if (!ann) {
            this.showEdit(null);
            return;
        }
        this.editType.value = ann.type;
        this.editComment.value = ann.comment || '';
    }

    /**
     * 列表项点击
     */
    _onItemClick(annId) {
        window.annotationStore.select(annId);
        window.canvasManager.selectAnnotation(annId);
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    renderSideBySide(annotations) {
        const panel = document.getElementById('sideBySidePanel');
        if (!panel) return;
        
        // Remove existing cards
        const oldCards = Array.from(panel.getElementsByClassName('side-card'));
        oldCards.forEach(c => c.remove());
        
        const visibleAnnotations = annotations.filter(ann => ann.type !== 'circle');

        if (visibleAnnotations.length === 0) {
            const svg = document.getElementById('sideBySideLines');
            if (svg) svg.innerHTML = '';
            return;
        }
        
        visibleAnnotations.forEach((ann, idx) => {
            const card = document.createElement('div');
            card.className = 'side-card';
            card.dataset.annId = ann.id;
            if (ann.id === window.annotationStore.selectedId) {
                card.classList.add('selected');
            }
            
            card.onclick = () => {
                this.openAnnotationEditor(ann.id);
            };
            
            const iconMap = { wavy: '∼', line: '—', circle: '○', star: '∼', check: '✓' };
            const typeLabelMap = { wavy: '点睛句', line: '行内批注', circle: '错字词', star: '点睛句', check: '翻译正确' };
            const icon = iconMap[ann.type] || '?';
            const typeLabel = typeLabelMap[ann.type] || ann.type;
            const sourceLabel = ann.source === 'ai' ? '🤖 AI' : '👤 教师';
            const detail = this._getAnnotationDetail(ann);
            const cardText = this._formatTeacherSideComment(ann, detail);
            
            card.innerHTML = `
                <span class="card-number">${idx + 1}</span>
                <div class="card-header">
                    <div style="display:flex;align-items:center;gap:6px;">
                        <span class="card-badge ${ann.type}">${icon}</span>
                        <span class="card-type ${ann.type}">${typeLabel}</span>
                    </div>
                    <span style="font-size:11px;color:#94a3b8;">${sourceLabel}</span>
                </div>
                <div class="card-comment">${this._escapeHtml(cardText || '(无批注)')}</div>
            `;
            
            panel.appendChild(card);
        });
        
        // Trigger position layout next frame
        requestAnimationFrame(() => {
            this.layoutSideBySideCards();
        });
    }

    _formatTeacherSideComment(ann, detail) {
        const raw = String(ann.comment || '').trim();
        if (ann.type === 'check') return raw || '这里翻译正确';
        const type = detail?.errorType || (ann.type === 'wavy' || ann.type === 'star' ? '点睛句' : '');
        const reason = String(detail?.reason || '').trim();
        if ((ann.type === 'wavy' || ann.type === 'star') && raw) {
            const cleaned = raw.replace(/^点睛句[★☆]?[:：]?/, '').trim();
            return `点睛句★\n${cleaned}`;
        }
        if (ann.type === 'line' && raw && !raw.startsWith('建议') && !raw.startsWith('可')) {
            return `建议改为\n“${raw.replace(/^改[:：]?/, '').replace(/^改为[:：]?/, '').trim()}”`;
        }
        if (raw && reason && !raw.includes(reason) && !raw.includes('因为')) {
            return `${type ? `${type}：` : ''}${raw}，因为${reason}`;
        }
        if (raw && type && !raw.startsWith(type)) {
            return `${type}：${raw}`;
        }
        if (raw) return raw;
        if (type || reason) return `${type || '建议'}：这里需要调整，${reason ? `因为${reason}` : '让表达更准确。'}`;
        return '';
    }

    _getAnnotationDetail(ann) {
        if (!ann) return null;
        if (ann.error_type || ann.reason) {
            return {
                errorType: ann.error_type || '',
                reason: ann.reason || ''
            };
        }
        if (!this.gradingData) return null;
        const analyses = this.gradingData.sentence_analyses || [];
        const sentenceIndex = ann.sentenceIndex ?? ann.sentence_index;
        const errorIndex = ann.errorIndex ?? ann.error_index;
        const sa = analyses[Number(sentenceIndex)];
        const err = sa && sa.errors ? sa.errors[Number(errorIndex)] : null;
        if (!err) {
            if (ann.type === 'wavy') {
                const comment = ann.comment || '';
                return comment ? { errorType: '点睛', reason: comment.replace(/^点睛句[:：]?/, '') } : null;
            }
            return null;
        }
        return {
            errorType: err.error_type || ann.label || '',
            reason: err.reason || ''
        };
    }

    updateSideCardSelection(selectedId) {
        const panel = document.getElementById('sideBySidePanel');
        if (!panel) return;
        
        const cards = Array.from(panel.getElementsByClassName('side-card'));
        cards.forEach(card => {
            const isSel = card.dataset.annId === selectedId;
            card.classList.toggle('selected', isSel);
            if (isSel) {
                card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        });
        
        this.layoutSideBySideCards();
    }

    layoutSideBySideCards() {
        const panel = document.getElementById('sideBySidePanel');
        if (!panel) return;
        const cards = Array.from(panel.getElementsByClassName('side-card'));
        if (cards.length === 0) {
            const svg = document.getElementById('sideBySideLines');
            if (svg) svg.innerHTML = '';
            return;
        }
        
        const canvasEl = window.canvasManager ? window.canvasManager.canvasEl : null;
        if (!canvasEl) return;
        const canvasRect = canvasEl.getBoundingClientRect();
        const panelRect = panel.getBoundingClientRect();
        const canvasTopInPanel = canvasRect.top - panelRect.top;
        const zoom = window.canvasManager.zoom;
        
        // 1. Gather items with target Y and heights
        const items = cards.map(card => {
            const id = card.dataset.annId;
            const ann = window.annotationStore.getById(id);
            let targetY = canvasTopInPanel + 10;
            if (ann) {
                const yImg = (ann.startY + ann.endY) / 2;
                targetY = canvasTopInPanel + yImg * zoom + 10;
            }
            return {
                id: id,
                card: card,
                ann: ann,
                targetY: targetY,
                height: card.offsetHeight || 118,
                currentY: targetY
            };
        });
        
        // Sort items by target Y
        items.sort((a, b) => a.targetY - b.targetY);
        
        // 2. Resolve overlap by pushing down
        const margin = 20;
        const minTop = 58;
        items.forEach(item => {
            if (item.currentY < minTop) item.currentY = minTop;
        });
        for (let i = 1; i < items.length; i++) {
            const prev = items[i - 1];
            const curr = items[i];
            if (curr.currentY < prev.currentY + prev.height + margin) {
                curr.currentY = prev.currentY + prev.height + margin;
            }
        }
        
        // 3. Prevent overflow bottom of the panel
        const maxBottom = panel.clientHeight - margin;
        for (let i = items.length - 1; i >= 0; i--) {
            const curr = items[i];
            if (curr.currentY + curr.height > maxBottom) {
                curr.currentY = maxBottom - curr.height;
                // adjust backwards
                if (i > 0) {
                    for (let j = i - 1; j >= 0; j--) {
                        const next = items[j + 1];
                        const p = items[j];
                        if (p.currentY + p.height + margin > next.currentY) {
                            p.currentY = next.currentY - p.height - margin;
                        }
                        if (p.currentY < minTop) p.currentY = minTop;
                    }
                }
            }
        }
        
        // 4. Position the elements
        items.forEach(item => {
            item.card.style.top = `${item.currentY}px`;
        });
        
        // 5. 不再绘制连接线，只通过画布编号与卡片编号对应。
        const svg = document.getElementById('sideBySideLines');
        if (!svg) return;
        svg.innerHTML = '';
    }
}

// 全局实例
window.sidePanel = new SidePanel();
