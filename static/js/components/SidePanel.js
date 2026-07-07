/**
 * 侧边面板组件 — 支持标注列表 + 批改报告 Tab 切换
 * 管理标注列表渲染、编辑面板交互、批改报告展示
 */
class SidePanel {
    constructor() {
        this.listEl = document.getElementById('annotationList');
        this.editPanel = document.getElementById('editPanel');
        this.editType = document.getElementById('editType');
        this.editComment = document.getElementById('editComment');
        this.panelCount = document.getElementById('panelCount');
        this._editingId = null;
        this._currentTab = 'annotations'; // 'annotations' | 'report'
        this.reportPanel = null;
    }

    init() {
        window.annotationStore.onChange((annotations) => this.renderList(annotations));
        window.annotationStore.onSelect((ann) => this.showEdit(ann));

        // 初始化批改报告面板
        this.reportPanel = new GradingReportPanel('gradingReport');

        // Tab 切换事件
        document.getElementById('tabAnnotations')?.addEventListener('click', () => this.switchTab('annotations'));
        document.getElementById('tabReport')?.addEventListener('click', () => this.switchTab('report'));
    }

    switchTab(tab) {
        this._currentTab = tab;
        document.getElementById('tabAnnotations').classList.toggle('active', tab === 'annotations');
        document.getElementById('tabReport').classList.toggle('active', tab === 'report');
        document.getElementById('panelAnnotations').style.display = tab === 'annotations' ? 'flex' : 'none';
        document.getElementById('panelReport').style.display = tab === 'report' ? 'flex' : 'none';
        document.getElementById('editPanel').classList.toggle('active', tab === 'annotations' && !!this._editingId);
    }

    /**
     * 加载批改数据并渲染报告
     */
    loadGradingData(gradingData) {
        if (this.reportPanel && gradingData) {
            this.reportPanel.render(gradingData);
        }
    }

    /**
     * 渲染标注列表
     */
    renderList(annotations) {
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
            this.editPanel.classList.remove('active');
            this._editingId = null;
            return;
        }

        this._editingId = ann.id;
        this.editType.value = ann.type;
        this.editComment.value = ann.comment || '';
        if (this._currentTab === 'annotations') {
            this.editPanel.classList.add('active');
        }
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
}

// 全局实例
window.sidePanel = new SidePanel();
