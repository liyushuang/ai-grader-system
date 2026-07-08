/**
 * 标注数据状态管理
 * 维护标注列表、选中状态、增删改查
 */
class AnnotationStore {
    constructor() {
        this.annotations = [];
        this.selectedId = null;
        this.onChangeCallbacks = [];
        this.onSelectCallbacks = [];
    }

    /** 从JSON数组加载标注 */
    load(annDataList) {
        this.annotations = annDataList.map((d, i) => ({
            id: d.id || `ann_${i}`,
            type: d.type === 'star' ? 'wavy' : d.type,
            startX: d.start_x,
            startY: d.start_y,
            endX: d.end_x,
            endY: d.end_y,
            source: d.source || 'ai',
            sentenceIndex: d.sentence_index,
            errorIndex: d.error_index,
            comment: d.comment || '',
            error_type: d.error_type || '',
            reason: d.reason || '',
            original_text: d.original_text || '',
            correct_text: d.correct_text || '',
            fabricObject: null,  // 关联的 Fabric 对象引用
        }));
        this.selectedId = null;
        this._notifyChange();
    }

    /** 获取所有标注 */
    getAll() { return this.annotations; }

    /** 获取选中标注 */
    getSelected() {
        if (!this.selectedId) return null;
        return this.annotations.find(a => a.id === this.selectedId) || null;
    }

    /** 按ID获取 */
    getById(id) {
        return this.annotations.find(a => a.id === id) || null;
    }

    /** 添加标注 */
    add(annotation) {
        const ann = {
            id: annotation.id || 'ann_' + Date.now(),
            type: annotation.type || 'line',
            startX: annotation.startX,
            startY: annotation.startY,
            endX: annotation.endX,
            endY: annotation.endY,
            source: annotation.source || 'teacher',
            sentenceIndex: annotation.sentenceIndex ?? null,
            errorIndex: annotation.errorIndex ?? null,
            comment: annotation.comment || '',
            error_type: annotation.error_type || '',
            reason: annotation.reason || '',
            original_text: annotation.original_text || '',
            correct_text: annotation.correct_text || '',
            fabricObject: annotation.fabricObject || null,
        };
        this.annotations.push(ann);
        this.select(ann.id);
        this._notifyChange();
        return ann;
    }

    /** 更新标注属性 */
    update(id, updates) {
        const ann = this.getById(id);
        if (!ann) return;
        Object.assign(ann, updates);
        if (updates.type || updates.comment) {
            ann.source = 'teacher';
        }
        this._notifyChange();
    }

    /** 删除标注 */
    remove(id) {
        const idx = this.annotations.findIndex(a => a.id === id);
        if (idx === -1) return null;
        const removed = this.annotations.splice(idx, 1)[0];
        if (this.selectedId === id) {
            this.selectedId = null;
            this._notifySelect();
        }
        this._notifyChange();
        return removed;
    }

    /** 选中标注 */
    select(id) {
        this.selectedId = id;
        this._notifySelect();
    }

    /** 取消选中 */
    deselect() {
        this.selectedId = null;
        this._notifySelect();
    }

    /** 切换到下一个标注 */
    selectNext() {
        if (this.annotations.length === 0) return;
        const idx = this.annotations.findIndex(a => a.id === this.selectedId);
        const nextIdx = (idx + 1) % this.annotations.length;
        this.select(this.annotations[nextIdx].id);
    }

    /** 获取标注数量 */
    get count() { return this.annotations.length; }

    /** 转为JSON数组（用于保存到后端） */
    toJSON() {
        return this.annotations.map(a => ({
            id: a.id,
            type: a.type,
            start_x: a.startX,
            start_y: a.startY,
            end_x: a.endX,
            end_y: a.endY,
            source: a.source,
            sentence_index: a.sentenceIndex,
            error_index: a.errorIndex,
            comment: a.comment,
            error_type: a.error_type,
            reason: a.reason,
            original_text: a.original_text,
            correct_text: a.correct_text,
        }));
    }

    // ── 事件回调 ──
    onChange(fn) { this.onChangeCallbacks.push(fn); }
    onSelect(fn) { this.onSelectCallbacks.push(fn); }

    _notifyChange() {
        this.onChangeCallbacks.forEach(fn => fn(this.annotations));
    }
    _notifySelect() {
        const sel = this.getSelected();
        this.onSelectCallbacks.forEach(fn => fn(sel));
    }
}

// 全局实例
window.annotationStore = new AnnotationStore();
