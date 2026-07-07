/**
 * 圆圈标注 — 用于错字/错词。
 */
class CircleAnnotation {
    static create(x1, y1, x2, y2, options = {}) {
        const color = '#EF4444';
        const left = Math.min(x1, x2);
        const top = Math.min(y1, y2);
        const width = Math.max(12, Math.abs(x2 - x1));
        const height = Math.max(12, Math.abs(y2 - y1));

        const glow = new fabric.Ellipse({
            left,
            top,
            rx: width / 2,
            ry: height / 2,
            originX: 'left',
            originY: 'top',
            fill: '',
            stroke: 'rgba(239, 68, 68, 0.35)',
            strokeWidth: 6,
            selectable: false,
            evented: false,
            visible: false,
            objectCaching: true,
        });

        const ellipse = new fabric.Ellipse({
            left,
            top,
            rx: width / 2,
            ry: height / 2,
            originX: 'left',
            originY: 'top',
            fill: '',
            stroke: color,
            strokeWidth: 2,
            strokeLineCap: 'round',
            objectCaching: true,
        });

        const group = new fabric.Group([glow, ellipse], {
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

        group.annotationType = 'circle';
        group._circleData = { x1: left, y1: top, x2: left + width, y2: top + height };
        group._circle = ellipse;
        group._glowCircle = glow;
        return group;
    }
}
