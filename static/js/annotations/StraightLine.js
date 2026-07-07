/**
 * 横线标注 — Fabric.js 轻量版
 * 红色 #EF4444, 线宽2px, 实线+两端小圆点, 不遮挡文字
 */
class StraightLine {
    static create(x1, y1, x2, y2, options = {}) {
        const lineColor = '#EF4444';
        
        // 发光边框（选中时）
        const glowLine = new fabric.Line([x1, y1, x2, y2], {
            stroke: 'rgba(239, 68, 68, 0.4)', strokeWidth: 5,
            selectable: false, evented: false, visible: false, objectCaching: true,
        });

        // 主线段
        const line = new fabric.Line([x1, y1, x2, y2], {
            stroke: lineColor, strokeWidth: 2, objectCaching: true,
            strokeLineCap: 'round',
        });

        // 两端小圆点
        const dR = 3;
        const leftDot = new fabric.Circle({
            left: x1 - dR, top: y1 - dR, radius: dR,
            fill: lineColor, hasBorders: false, hasControls: false,
            selectable: false, evented: false,
        });
        const rightDot = new fabric.Circle({
            left: x2 - dR, top: y2 - dR, radius: dR,
            fill: lineColor, hasBorders: false, hasControls: false,
            selectable: false, evented: false,
        });

        const group = new fabric.Group([glowLine, line, leftDot, rightDot], {
            selectable: true, evented: true,
            hasControls: false, hasBorders: false,
            borderColor: lineColor, borderScaleFactor: 1,
            padding: 3, lockRotation: true, lockScalingY: true,
            ...options,
        });

        group.annotationType = 'line';
        group._lineData = { x1, y1, x2, y2 };
        group._mainLine = line;
        group._glowLine = glowLine;
        group._leftDot = leftDot;
        group._rightDot = rightDot;

        return group;
    }
}
