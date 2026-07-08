/**
 * Fabric.js Canvas 管理器
 * 负责：加载原图、渲染标注、处理鼠标交互、管理标注对象生命周期
 */
class CanvasManager {
    constructor() {
        this.canvasEl = document.getElementById('annotationCanvas');
        this.fabric = null;
        this.zoom = 1;
        this.isDrawing = false;
        this.drawStartX = 0;
        this.drawStartY = 0;
        this.drawPreview = null;
        this.viewportPadding = 10;
    }

    /**
     * 初始化 Fabric Canvas
     */
    init() {
        const area = document.getElementById('canvasArea');
        this.fabric = new fabric.Canvas(this.canvasEl, {
            width: area.clientWidth,
            height: area.clientHeight,
            selection: false,
            preserveObjectStacking: true,
            fireRightClick: true,
            stopContextMenu: false,
        });

        this._bindEvents();
        this._updateStatusBar();
    }

    /**
     * 加载原图
     */
    loadImage(base64Data) {
        return new Promise((resolve, reject) => {
            // 检测图片格式
            let mimeType = 'image/jpeg';
            if (base64Data.startsWith('data:image/png')) mimeType = 'image/png';
            else if (base64Data.startsWith('data:image/')) {
                const m = base64Data.match(/^data:image\/([^;]+)/);
                if (m) mimeType = 'image/' + m[1];
            }
            
            // 如果base64已经包含data URI前缀，直接使用；否则添加前缀
            const dataUrl = base64Data.startsWith('data:') 
                ? base64Data 
                : 'data:' + mimeType + ';base64,' + base64Data;
            
            fabric.Image.fromURL(dataUrl, (img) => {
                if (!img || !img.width) {
                    reject(new Error('图片加载失败'));
                    return;
                }
                
                // 适配画布大小
                const area = document.getElementById('canvasArea');
                const maxW = area.clientWidth - 40;
                const maxH = area.clientHeight - 40;
                
                let scale = 1;
                if (img.width > maxW || img.height > maxH) {
                    scale = Math.min(maxW / img.width, maxH / img.height);
                }
                
                img.set({
                    scaleX: scale,
                    scaleY: scale,
                    selectable: false,
                    evented: false,
                    hasControls: false,
                    lockMovementX: true,
                    lockMovementY: true,
                });

                this.fabric.setDimensions({
                    width: img.width * scale + 20,
                    height: img.height * scale + 20,
                });
                
                this.fabric.backgroundImage = img;
                this.fabric.renderAll();
                this.zoom = scale;
                
                // 只用 viewport 负责图片和标注的统一外边距，避免标注坐标重复偏移。
                this.fabric.viewportTransform = [1, 0, 0, 1, this.viewportPadding, this.viewportPadding];
                this.fabric.renderAll();
                
                this._updateStatusBar();
                resolve(img);
            }, { crossOrigin: 'anonymous' });
        });
    }

    /**
     * 渲染所有标注
     */
    renderAnnotations(annotations) {
        // 清除旧标注
        this.fabric.getObjects().forEach(obj => {
            if (obj.annotationType) {
                this.fabric.remove(obj);
            }
        });

        annotations.forEach((ann) => {
            const fabricObj = this._createAnnotationObject(ann);
            if (fabricObj) {
                fabricObj.annId = ann.id;
                this.fabric.add(fabricObj);
                ann.fabricObject = fabricObj;
                this._addInlineCommentObject(ann);
            }
        });

        this.fabric.renderAll();
        this._updateStatusBar();
    }

    _imageToSceneCoords(x, y) {
        return {
            x: x * this.zoom,
            y: y * this.zoom,
        };
    }

    _sceneToImageCoords(sceneX, sceneY) {
        return {
            x: Math.round(sceneX / this.zoom),
            y: Math.round(sceneY / this.zoom),
        };
    }

    _screenToImageCoords(screenX, screenY) {
        const vt = this.fabric?.viewportTransform || [1, 0, 0, 1, 0, 0];
        return {
            x: Math.round((screenX - vt[4]) / this.zoom),
            y: Math.round((screenY - vt[5]) / this.zoom),
        };
    }

    _getDisplayYOffset(_ann) {
        return 0;
    }

    /**
     * 创建单个标注的 Fabric 对象
     * 后端坐标已经是原图上的最终标注位置，前端只做缩放映射。
     */
    _createAnnotationObject(ann) {
        const p1 = this._imageToSceneCoords(ann.startX, ann.startY);
        const p2 = this._imageToSceneCoords(ann.endX, ann.endY);
        const sx1 = p1.x;
        const sy1 = p1.y;
        const sx2 = p2.x;
        const sy2 = p2.y;

        let obj = null;
        switch (ann.type) {
            case 'wavy':
                obj = WavyLine.create(sx1, sy1, sx2, sy2);
                break;
            case 'line':
                obj = StraightLine.create(sx1, sy1, sx2, sy2);
                break;
            case 'circle':
                obj = CircleAnnotation.create(sx1, sy1, sx2, sy2, {
                    correctionText: this._getCircleCorrectionText(ann),
                });
                break;
            case 'star':
                obj = WavyLine.create(sx1, sy1, sx2 || sx1 + 80, sy1);
                break;
            case 'check':
                obj = CheckAnnotation.create(sx1, sy1, sx2, sy2);
                break;
        }
        return obj;
    }

    _addInlineCommentObject(ann) {
        if (!['line', 'wavy'].includes(ann.type)) return null;
        const p2 = this._imageToSceneCoords(ann.endX, ann.endY);
        const objects = this._createInlineCommentObjects(ann, p2.x, p2.y);
        if (!objects.length) return null;
        objects.forEach(obj => {
            obj.annId = ann.id;
            obj.annotationType = 'inlineComment';
            obj.relatedAnnotationType = ann.type;
            this.fabric.add(obj);
        });
        ann.inlineCommentObject = objects[objects.length - 1];
        return ann.inlineCommentObject;
    }

    _createInlineCommentObjects(ann, x, y) {
        const rawText = this._getInlineCommentText(ann);
        const isPinpoint = this._shouldKeepCommentNearText(ann);
        const text = isPinpoint ? rawText : this._getLineEndCommentText(ann, rawText);
        if (!text) return [];

        const fill = (ann.type === 'wavy' || ann.type === 'star')
            ? '#10B981'
            : (ann.error_type === '漏译' ? '#2563EB' : '#E11D2E');
        const style = {
            top: y - 24,
            originX: 'left',
            originY: 'top',
            fill,
            fontSize: isPinpoint ? 17 : 15,
            fontWeight: '700',
            fontFamily: '"PingFang SC", "Microsoft YaHei", sans-serif',
            stroke: '#fff',
            strokeWidth: 2,
            paintFirst: 'stroke',
            selectable: true,
            evented: true,
            hasControls: false,
            hasBorders: false,
            hoverCursor: 'pointer',
            objectCaching: true,
        };
        if (isPinpoint) {
            return [new fabric.Text(text, { left: x + 10, ...style })];
        }

        const labelLeft = this._getLineEndCommentLeft();
        const labelTop = y - 22;
        const label = new fabric.Textbox(text, {
            left: labelLeft,
            top: labelTop,
            width: this._getLineEndCommentWidth(),
            textAlign: 'left',
            splitByGrapheme: true,
            ...style,
        });
        return [label];
    }

    _shouldKeepCommentNearText(ann) {
        const text = `${ann.error_type || ''} ${ann.comment || ''} ${ann.reason || ''}`;
        return /错字|错别字|不规范字|漏字/.test(text);
    }

    _getLineEndCommentLeft() {
        const bg = this.fabric?.backgroundImage;
        const imageW = bg ? bg.getScaledWidth() : 420;
        return Math.max(8, imageW - this._getLineEndCommentWidth() - 16);
    }

    _getLineEndCommentWidth() {
        const bg = this.fabric?.backgroundImage;
        const imageW = bg ? bg.getScaledWidth() : 420;
        return Math.max(110, Math.min(150, imageW * 0.28));
    }

    _getInlineCommentText(ann) {
        const type = ann.error_type || '';
        const correct = String(ann.correct_text || '').trim();
        const comment = String(ann.comment || '').trim();
        if (type === '漏译' && correct) return `补：${correct}`;
        if (comment.startsWith('补') || comment.includes('漏译')) {
            return comment.replace(/^建议/, '').slice(0, 16);
        }
        if (comment.length <= 12 && !comment.includes('：')) return comment;
        const compact = comment
            .replace(/^建议改为[:：]?/, '改：')
            .replace(/^错字[:：]?/, '')
            .replace(/^实词错误[:：]?/, '')
            .trim();
        return compact.length <= 14 ? compact : '';
    }

    _getLineEndCommentText(ann, text) {
        const type = String(ann.error_type || '');
        const original = String(ann.original_text || '').trim();
        const correct = String(ann.correct_text || '').trim();
        const comment = String(text || ann.comment || '').trim();
        if (type === '漏译' && (correct || original)) return `补：${correct || original}`;
        if (ann.type === 'wavy') return comment.startsWith('点睛句') ? '点睛句★' : '点睛句★';
        if (type.includes('实词') && original) return this._compactLineEndText(`${original}误`);
        if (type.includes('句意')) return '句意不准';
        if (type.includes('语义') || comment.includes('重复')) return '语义重复';
        if (type.includes('语序')) return '语序不当';
        if (original.includes('形异') || correct.includes('形态') || comment.includes('形异')) return '形态表达';
        if (original && correct) return this._compactLineEndText(`${original}误`);
        if (comment) return this._compactLineEndText(comment);
        return '';
    }

    _compactLineEndText(text) {
        const compact = String(text || '')
            .replace(/^实词错误[:：]?/, '')
            .replace(/^句意错误[:：]?/, '')
            .replace(/^语义重复[:：]?/, '语义重复')
            .replace(/^建议改为[:：]?/, '改：')
            .replace(/腰间的/g, '')
            .replace(/玉佩和玉环相碰撞/g, '玉佩相撞')
            .replace(/相碰撞/g, '相撞')
            .replace(/的声音/g, '')
            .replace(/：.*$/, '误')
            .trim();
        return compact.length > 6 ? compact.slice(0, 6) + '…' : compact;
    }

    _getCircleCorrectionText(ann) {
        if (ann.correct_text) {
            return String(ann.correct_text).trim();
        }
        const comment = ann.comment || '';
        const arrow = comment.includes('→') ? comment.split('→').pop() : '';
        if (arrow) return arrow.trim().replace(/[。；;，,].*$/, '');
        const shouldWrite = comment.match(/应写作(.+)$/);
        if (shouldWrite) return shouldWrite[1].trim();
        const changeTo = comment.match(/这里改成(.+)$/);
        if (changeTo) return changeTo[1].trim();
        return comment
            .replace(/^建议改为[:：]?/, '')
            .replace(/^建议改[:：]?/, '')
            .replace(/^改为[:：]?/, '')
            .replace(/^改[:：]?/, '')
            .replace(/^错字[:：]?/, '')
            .trim();
    }

    _attachNumberBadge(group, x, y, index) {
        const radius = 10;
        const badge = new fabric.Circle({
            left: x - radius - 2,
            top: y - radius - 18,
            radius,
            fill: '#60A5FA',
            stroke: '#fff',
            strokeWidth: 2,
            selectable: false,
            evented: false,
            objectCaching: true,
        });
        const label = new fabric.Text(String(index), {
            left: x - 2,
            top: y - 18,
            originX: 'center',
            originY: 'center',
            fill: '#fff',
            fontSize: 12,
            fontWeight: '700',
            fontFamily: 'Arial, sans-serif',
            selectable: false,
            evented: false,
            objectCaching: true,
        });

        group.addWithUpdate(badge);
        group.addWithUpdate(label);
        group._numberBadge = badge;
        group._numberLabel = label;
    }

    /**
     * 添加单个标注到画布
     */
    addAnnotation(ann) {
        const obj = this._createAnnotationObject(ann);
        if (obj) {
            obj.annId = ann.id;
            this.fabric.add(obj);
            ann.fabricObject = obj;
            this._addInlineCommentObject(ann);
            this.fabric.setActiveObject(obj);
            this.fabric.renderAll();
            this._updateStatusBar();
        }
        return obj;
    }

    /**
     * 移除标注
     */
    removeAnnotation(annId) {
        const obj = this.fabric.getObjects().find(o => o.annId === annId);
        this.fabric.getObjects()
            .filter(o => o.annotationType === 'inlineComment' && o.annId === annId)
            .forEach(o => this.fabric.remove(o));
        if (obj) {
            this.fabric.remove(obj);
            if (window.annotationStore) {
                this.renderAnnotations(window.annotationStore.getAll());
            } else {
                this.fabric.renderAll();
                this._updateStatusBar();
            }
        }
    }

    /**
     * 更新标注在Canvas上的样式（类型切换时）
     */
    updateAnnotationStyle(ann) {
        const oldObj = this.fabric.getObjects().find(o => o.annId === ann.id);
        if (!oldObj) return;
        
        const p1 = this._imageToSceneCoords(ann.startX, ann.startY);
        const p2 = this._imageToSceneCoords(ann.endX, ann.endY);
        const sx1 = p1.x;
        const sy1 = p1.y;
        const sx2 = p2.x;
        const sy2 = p2.y;

        let newObj = null;
        switch (ann.type) {
            case 'wavy': newObj = WavyLine.create(sx1, sy1, sx2, sy2); break;
            case 'line': newObj = StraightLine.create(sx1, sy1, sx2, sy2); break;
            case 'circle': newObj = CircleAnnotation.create(sx1, sy1, sx2, sy2, {
                correctionText: this._getCircleCorrectionText(ann),
            }); break;
            case 'star': newObj = WavyLine.create(sx1, sy1, sx2 || sx1 + 80, sy1); break;
            case 'check': newObj = CheckAnnotation.create(sx1, sy1, sx2, sy2); break;
        }

        if (newObj) {
            newObj.annId = ann.id;
            const idx = this.fabric.getObjects().indexOf(oldObj);
            this.fabric.remove(oldObj);
            this.fabric.getObjects()
                .filter(o => o.annotationType === 'inlineComment' && o.annId === ann.id)
                .forEach(o => this.fabric.remove(o));
            this.fabric.insertAt(idx, newObj);
            ann.fabricObject = newObj;
            this._addInlineCommentObject(ann);
            this.fabric.setActiveObject(newObj);
            this.fabric.renderAll();
        }
    }

    /**
     * 选中Canvas上的标注对象
     */
    selectAnnotation(annId) {
        const obj = this.fabric.getObjects().find(o => o.annId === annId);
        if (obj) {
            this.fabric.setActiveObject(obj);
            this.fabric.renderAll();
        }
    }

    /**
     * 取消所有选中
     */
    deselectAll() {
        this.fabric.discardActiveObject();
        this.fabric.renderAll();
    }

    /**
     * 根据Canvas坐标反算原图坐标
     */
    canvasToImageCoords(canvasX, canvasY) {
        return this._sceneToImageCoords(canvasX, canvasY);
    }

    /**
     * 导出带标注的图片 (Data URL)
     */
    exportImage(format = 'png') {
        return this.fabric.toDataURL({
            format: format,
            quality: 0.95,
            multiplier: 1 / this.zoom,  // 按原图分辨率导出
        });
    }

    // ── 事件绑定 ──

    _bindEvents() {
        this.fabric.on('mouse:down', (opt) => this._onMouseDown(opt));
        this.fabric.on('mouse:move', (opt) => this._onMouseMove(opt));
        this.fabric.on('mouse:up', (opt) => this._onMouseUp(opt));
        this.fabric.on('selection:created', (opt) => this._onObjectSelected(opt));
        this.fabric.on('selection:updated', (opt) => this._onObjectSelected(opt));
        this.fabric.on('selection:cleared', () => this._onSelectionCleared());
        this.fabric.on('object:modified', (opt) => this._onObjectModified(opt));
        this.fabric.on('mouse:dblclick', (opt) => this._onDoubleClick(opt));

        // 键盘快捷键
        document.addEventListener('keydown', (e) => this._onKeyDown(e));

        // 鼠标滚轮缩放
        this.canvasEl.addEventListener('wheel', (e) => {
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
                const delta = e.deltaY > 0 ? 0.9 : 1.1;
                this.zoomCanvas(delta);
            }
        }, { passive: false });

        // 窗口大小变化
        window.addEventListener('resize', () => this._onResize());

        // 更新坐标状态栏
        this.canvasEl.addEventListener('mousemove', (e) => {
            const rect = this.canvasEl.getBoundingClientRect();
            const imgCoords = this._screenToImageCoords(e.clientX - rect.left, e.clientY - rect.top);
            document.getElementById('statusCoords').textContent = 
                `坐标: (${imgCoords.x}, ${imgCoords.y})`;
        });
    }

    _onMouseDown(opt) {
        if (currentTool === 'select') return;

        const pointer = this.fabric.getPointer(opt.e);
        this.isDrawing = true;
        this.drawStartX = pointer.x;
        this.drawStartY = pointer.y;
    }

    _onMouseMove(opt) {
        if (!this.isDrawing) return;

        const pointer = this.fabric.getPointer(opt.e);
        
        // 移除旧预览
        if (this.drawPreview) {
            this.fabric.remove(this.drawPreview);
        }

        // 绘制虚线预览
        const dashPattern = [6, 4];
        switch (currentTool) {
            case 'wavy':
                this.drawPreview = new fabric.Line(
                    [this.drawStartX, this.drawStartY, pointer.x, pointer.y],
                    { stroke: '#10B981', strokeWidth: 2, strokeDashArray: dashPattern, selectable: false, evented: false }
                );
                break;
            case 'line':
                this.drawPreview = new fabric.Line(
                    [this.drawStartX, this.drawStartY, pointer.x, pointer.y],
                    { stroke: '#E11D2E', strokeWidth: 2.4, strokeDashArray: dashPattern, selectable: false, evented: false }
                );
                break;
            case 'circle':
                this.drawPreview = new fabric.Ellipse({
                    left: Math.min(this.drawStartX, pointer.x),
                    top: Math.min(this.drawStartY, pointer.y),
                    rx: Math.max(6, Math.abs(pointer.x - this.drawStartX) / 2),
                    ry: Math.max(6, Math.abs(pointer.y - this.drawStartY) / 2),
                    originX: 'left',
                    originY: 'top',
                    fill: 'rgba(225,29,46,0.04)',
                    stroke: '#E11D2E',
                    strokeWidth: 2,
                    strokeDashArray: dashPattern,
                    selectable: false,
                    evented: false,
                });
                break;
            case 'star':
            case 'check':
                this.drawPreview = new fabric.Circle({
                    left: pointer.x - 10, top: pointer.y - 10,
                    radius: 10, fill: currentTool === 'check' ? 'rgba(225,29,46,0.18)' : 'rgba(245,158,11,0.3)',
                    stroke: currentTool === 'check' ? '#E11D2E' : '#F59E0B', strokeWidth: 2, strokeDashArray: dashPattern,
                    selectable: false, evented: false,
                });
                break;
        }

        if (this.drawPreview) {
            this.fabric.add(this.drawPreview);
            this.fabric.renderAll();
        }
    }

    _onMouseUp(opt) {
        if (!this.isDrawing) return;
        this.isDrawing = false;

        // 移除预览
        if (this.drawPreview) {
            this.fabric.remove(this.drawPreview);
            this.drawPreview = null;
        }

        const pointer = this.fabric.getPointer(opt.e);
        const dx = pointer.x - this.drawStartX;
        const dy = pointer.y - this.drawStartY;
        const dist = Math.sqrt(dx * dx + dy * dy);

        // 最小距离阈值（防止误点）
        if (['star', 'check'].includes(currentTool) ? dist < 5 : dist < 12) {
            this.fabric.renderAll();
            return;
        }

        // 反算原图坐标
        const startImg = this.canvasToImageCoords(this.drawStartX, this.drawStartY);
        const endImg = this.canvasToImageCoords(pointer.x, pointer.y);

        // 创建标注
        const ann = {
            type: currentTool,
            startX: startImg.x,
            startY: startImg.y,
            endX: currentTool === 'star' ? startImg.x : endImg.x,
            endY: currentTool === 'star' ? startImg.y : endImg.y,
            source: 'teacher',
            comment: '',
        };

        const created = window.annotationStore.add(ann);
        this.addAnnotation(created);
        if (window.sidePanel && typeof window.sidePanel.openAnnotationEditor === 'function') {
            window.sidePanel.openAnnotationEditor(created.id);
        }

        // 记录撤销
        window.undoManager.execute({
            type: 'add',
            annotationId: created.id,
            execute: () => {},
            undo: () => {
                window.annotationStore.remove(created.id);
                this.removeAnnotation(created.id);
            },
        });
    }

    _onObjectSelected(opt) {
        const obj = opt.selected?.[0];
        if (obj && obj.annId) {
            // 显示发光效果
            this._setGlow(obj, true);
            window.annotationStore.select(obj.annId);
        }
    }

    _onSelectionCleared() {
        // 清除所有发光
        this.fabric.getObjects().forEach(obj => {
            if (obj.annotationType) this._setGlow(obj, false);
        });
        window.annotationStore.deselect();
    }

    /** 设置发光效果 */
    _setGlow(group, active) {
        const glowObj = group._glowPath || group._glowLine || group._glowPoly || group._glowCircle;
        if (glowObj) {
            glowObj.set({ visible: active });
        }
        if (active) {
            group.set({ borderColor: '#4a90d9', borderScaleFactor: 1.2 });
        } else {
            const colors = { wavy: '#10B981', line: '#EF4444', circle: '#EF4444', star: '#10B981', check: '#E11D2E' };
            group.set({ borderColor: colors[group.annotationType] || '#333', borderScaleFactor: 1 });
        }
        this.fabric.renderAll();
    }

    _onObjectModified(opt) {
        const obj = opt.target;
        if (!obj || !obj.annId) return;

        const ann = window.annotationStore.getById(obj.annId);
        if (!ann) return;

        // 获取新位置（通过 getBoundingRect）
        const bounds = obj.getBoundingRect();
        const imgCoords1 = this.canvasToImageCoords(bounds.left, bounds.top);
        const imgCoords2 = this.canvasToImageCoords(bounds.left + bounds.width, bounds.top + bounds.height);

        const oldData = {
            startX: ann.startX, startY: ann.startY,
            endX: ann.endX, endY: ann.endY,
        };

        // 更新标注数据
        if (ann.type === 'star') {
            window.annotationStore.update(obj.annId, {
                startX: imgCoords1.x, startY: imgCoords1.y,
                endX: imgCoords1.x, endY: imgCoords1.y,
            });
        } else {
            window.annotationStore.update(obj.annId, {
                startX: imgCoords1.x, startY: imgCoords1.y,
                endX: imgCoords2.x, endY: imgCoords2.y,
            });
        }

        this.renderAnnotations(window.annotationStore.getAll());
        this.selectAnnotation(obj.annId);

        // 撤销记录
        window.undoManager.execute({
            type: 'move',
            annotationId: obj.annId,
            previousState: oldData,
            newState: { startX: ann.startX, startY: ann.startY, endX: ann.endX, endY: ann.endY },
            execute: () => {},
            undo: () => {
                window.annotationStore.update(obj.annId, oldData);
                // 重新渲染位置
                const a = window.annotationStore.getById(obj.annId);
                if (a) window.canvasManager.updateAnnotationStyle(a);
            },
        });
    }

    _onDoubleClick(opt) {
        const target = opt.target;
        if (target && target.annId) {
            // 显示上下文菜单
            const menu = document.getElementById('contextMenu');
            menu.style.display = 'block';
            menu.style.left = opt.e.clientX + 'px';
            menu.style.top = opt.e.clientY + 'px';
            menu._annId = target.annId;
            
            setTimeout(() => {
                const hideMenu = () => {
                    menu.style.display = 'none';
                    document.removeEventListener('click', hideMenu);
                };
                document.addEventListener('click', hideMenu);
            }, 0);
        }
    }

    _onKeyDown(e) {
        // 快捷键（不在输入框内）
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

        switch (e.key) {
            case 'Delete':
            case 'Backspace':
                e.preventDefault();
                deleteSelected();
                break;
            case 'Escape':
                setTool('select');
                break;
            case 'w':
            case 'W':
                setTool('wavy');
                break;
            case 'l':
            case 'L':
                setTool('line');
                break;
            case 'c':
            case 'C':
                setTool('circle');
                break;
            case 'k':
            case 'K':
                setTool('check');
                break;
            case 'v':
            case 'V':
                setTool('select');
                break;
            case 'z':
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    if (e.shiftKey) {
                        redo();
                    } else {
                        undo();
                    }
                }
                break;
            case 'y':
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    redo();
                }
                break;
        }
    }

    _onResize() {
        if (!this.fabric) return;
        const area = document.getElementById('canvasArea');
        const bg = this.fabric.backgroundImage;
        if (bg) {
            this.fabric.setDimensions({
                width: bg.getScaledWidth() + 20,
                height: bg.getScaledHeight() + 20,
            });
        } else {
            this.fabric.setDimensions({
                width: Math.max(320, area.clientWidth - 40),
                height: Math.max(320, area.clientHeight - 40),
            });
        }
        this.fabric.renderAll();
    }

    /** 缩放画布 */
    zoomCanvas(factor) {
        const newZoom = this.zoom * factor;
        if (newZoom < 0.2 || newZoom > 3) return;
        
        const center = this.fabric.getCenter();
        const point = new fabric.Point(center.left, center.top);
        this.fabric.zoomToPoint(point, factor);
        this.zoom = newZoom;
        this._updateStatusBar();
    }

    _updateStatusBar() {
        document.getElementById('statusZoom').textContent = Math.round(this.zoom * 100) + '%';
        document.getElementById('statusAnns').textContent = 
            '标注: ' + window.annotationStore.count;
    }
}

// 全局实例
window.canvasManager = new CanvasManager();
