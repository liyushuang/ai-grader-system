/**
 * 波浪线标注 — Fabric.js 轻量版
 * 翠绿色 #10B981, 线宽2px, 小振幅平滑波浪, 不遮挡文字
 */
class WavyLine {
    static create(x1, y1, x2, y2, options = {}) {
        const amplitude = 3;  // 小振幅，避免遮挡
        const length = x2 - x1;
        const baseY = y1;
        const color = '#10B981';
        
        // 使用二次贝塞尔曲线生成平滑波浪
        let pathStr = `M ${x1} ${baseY}`;
        const steps = Math.max(Math.floor(Math.abs(length) / 4), 8);
        const stepSize = length / steps;
        
        for (let i = 1; i <= steps; i++) {
            const x = x1 + i * stepSize;
            const prevX = x1 + (i - 1) * stepSize;
            const midX = (prevX + x) / 2;
            const midY = baseY + amplitude * Math.sin((midX - x1) / length * Math.PI * 4);
            const endY = baseY + amplitude * Math.sin((x - x1) / length * Math.PI * 4);
            pathStr += ` Q ${midX.toFixed(1)} ${midY.toFixed(1)}, ${x.toFixed(1)} ${endY.toFixed(1)}`;
        }
        
        // 主波浪线（细线，不遮挡）
        const path = new fabric.Path(pathStr, {
            fill: '',
            stroke: color,
            strokeWidth: 2,  // 细线
            strokeLineCap: 'round',
            strokeLineJoin: 'round',
            objectCaching: true,
        });

        // 选中时发光效果
        const glowPath = new fabric.Path(pathStr, {
            fill: '',
            stroke: 'rgba(16, 185, 129, 0.4)',
            strokeWidth: 6,
            strokeLineCap: 'round',
            strokeLineJoin: 'round',
            objectCaching: true,
            visible: false,
            selectable: false,
            evented: false,
        });

        const group = new fabric.Group([glowPath, path], {
            selectable: true, evented: true,
            hasControls: false, hasBorders: true,
            borderColor: color, borderScaleFactor: 1,
            padding: 4, lockRotation: true, lockScalingY: true,
            ...options,
        });

        group.annotationType = 'wavy';
        group._wavyData = { x1, y1: baseY, x2, y2: baseY, amplitude };
        group._wavePath = path;
        group._glowPath = glowPath;

        return group;
    }
}
