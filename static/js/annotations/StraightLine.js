/**
 * 横线标注 — Fabric.js 轻量版
 * 红色 #EF4444, 线宽2px, 实线+两端小圆点, 不遮挡文字
 */
class StraightLine {
    static create(x1, y1, x2, y2, options = {}) {
        const lineColor = '#EF4444';

        const pathStr = StraightLine._handPath(x1, y1, x2, y2);
        const glowLine = new fabric.Path(pathStr, {
            fill: '',
            stroke: 'rgba(239, 68, 68, 0.4)', strokeWidth: 5,
            strokeLineCap: 'round',
            strokeLineJoin: 'round',
            selectable: false, evented: false, visible: false, objectCaching: true,
        });

        const line = new fabric.Path(pathStr, {
            fill: '',
            stroke: lineColor, strokeWidth: 2, objectCaching: true,
            strokeLineCap: 'round',
            strokeLineJoin: 'round',
        });

        const group = new fabric.Group([glowLine, line], {
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

        return group;
    }

    static _handPath(x1, y1, x2, y2) {
        const dx = x2 - x1;
        const dy = y2 - y1;
        const len = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const nx = -dy / len;
        const ny = dx / len;
        const steps = Math.max(3, Math.floor(len / 36));
        let path = `M ${x1.toFixed(1)} ${y1.toFixed(1)}`;
        for (let i = 1; i <= steps; i++) {
            const t = i / steps;
            const wobble = Math.sin((x1 + y1 + i * 17) * 0.37) * 1.4;
            const x = x1 + dx * t + nx * wobble;
            const y = y1 + dy * t + ny * wobble;
            path += ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
        }
        return path;
    }
}
