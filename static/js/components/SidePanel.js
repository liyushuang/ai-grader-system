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
        if (this.reportPanel && gradingData) {
            this.reportPanel.render(gradingData);
        }
    }

    clearAllViews() {
        this.renderSideBySide([]);
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

            const iconMap = { wavy: ['∼', 'wavy'], line: ['—', 'line'], star: ['★', 'star'] };
            const [icon, cls] = iconMap[ann.type] || ['?', 'line'];
            const typeLabelMap = { wavy: '波浪线·精彩句', line: '横线·问题句', star: '星星·点睛句' };
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
        
        if (annotations.length === 0) {
            const svg = document.getElementById('sideBySideLines');
            if (svg) svg.innerHTML = '';
            return;
        }
        
        annotations.forEach((ann, idx) => {
            const card = document.createElement('div');
            card.className = 'side-card';
            card.dataset.annId = ann.id;
            if (ann.id === window.annotationStore.selectedId) {
                card.classList.add('selected');
            }
            
            card.onclick = () => {
                this.openAnnotationEditor(ann.id);
            };
            
            const iconMap = { wavy: '∼', line: '—', star: '★' };
            const typeLabelMap = { wavy: '精彩', line: '纠错', star: '点睛' };
            const icon = iconMap[ann.type] || '?';
            const typeLabel = typeLabelMap[ann.type] || ann.type;
            const sourceLabel = ann.source === 'ai' ? '🤖 AI' : '👤 教师';
            
            card.innerHTML = `
                <span class="card-number">${idx + 1}</span>
                <div class="card-header">
                    <div style="display:flex;align-items:center;gap:6px;">
                        <span class="card-badge ${ann.type}">${icon}</span>
                        <span class="card-type ${ann.type}">${typeLabel}</span>
                    </div>
                    <span style="font-size:11px;color:#94a3b8;">${sourceLabel}</span>
                </div>
                <div class="card-comment">${this._escapeHtml(ann.comment || '(无批注)')}</div>
            `;
            
            panel.appendChild(card);
        });
        
        // Trigger position layout next frame
        requestAnimationFrame(() => {
            this.layoutSideBySideCards();
        });
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
                height: card.offsetHeight || 90,
                currentY: targetY
            };
        });
        
        // Sort items by target Y
        items.sort((a, b) => a.targetY - b.targetY);
        
        // 2. Resolve overlap by pushing down
        const margin = 14;
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
        
        // 5. Draw connecting curves in SVG
        const svg = document.getElementById('sideBySideLines');
        if (!svg) return;
        svg.innerHTML = '';
        
        items.forEach(item => {
            if (!item.ann) return;
            const yImg = (item.ann.startY + item.ann.endY) / 2;
            const targetY = canvasTopInPanel + yImg * zoom + 10;
            
            // card connection Y
            const cardY = item.currentY + 15;
            
            const colorMap = { wavy: '#10b981', line: '#ef4444', star: '#f59e0b' };
            const color = colorMap[item.ann.type] || '#3b82f6';
            const isSelected = item.id === window.annotationStore.selectedId;
            
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            const d = `M 0 ${targetY} C 14 ${targetY}, 16 ${cardY}, 32 ${cardY}`;
            path.setAttribute('d', d);
            path.setAttribute('stroke', color);
            path.setAttribute('stroke-width', isSelected ? '2' : '1.2');
            path.setAttribute('fill', 'none');
            path.setAttribute('stroke-dasharray', item.ann.source === 'ai' ? '3,3' : 'none');
            path.setAttribute('opacity', isSelected ? '1' : '0.6');
            svg.appendChild(path);
        });
    }
}

// 全局实例
window.sidePanel = new SidePanel();
