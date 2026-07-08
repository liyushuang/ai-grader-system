/**
 * 对勾标注 — 用于重点字词翻译正确的位置。
 */
class CheckAnnotation {
    static create(x1, y1, x2, y2, options = {}) {
        const color = '#E11D2E';
        const width = Math.max(28, Math.abs(x2 - x1));
        const height = Math.max(18, Math.abs(y2 - y1));
        const left = Math.min(x1, x2);
        const top = Math.min(y1, y2);

        const points = [
            { x: left, y: top + height * 0.56 },
            { x: left + width * 0.28, y: top + height },
            { x: left + width, y: top },
        ];

        const glow = new fabric.Polyline(points, {
            fill: '',
            stroke: 'rgba(225,29,46,0.28)',
            strokeWidth: 8,
            strokeLineCap: 'round',
            strokeLineJoin: 'round',
            selectable: false,
            evented: false,
            visible: false,
            objectCaching: true,
        });

        const check = new fabric.Polyline(points, {
            fill: '',
            stroke: color,
            strokeWidth: 4,
            strokeLineCap: 'round',
            strokeLineJoin: 'round',
            objectCaching: true,
        });

        const group = new fabric.Group([glow, check], {
            selectable: true,
            evented: true,
            hasControls: false,
            hasBorders: false,
            borderColor: color,
            borderScaleFactor: 1,
            padding: 4,
            lockRotation: true,
            ...options,
        });

        group.annotationType = 'check';
        group._checkData = { x1: left, y1: top, x2: left + width, y2: top + height };
        group._check = check;
        group._glowPoly = glow;
        return group;
    }
}
