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
        
        // 生成带轻微手写抖动的波浪线。
        let pathStr = `M ${x1} ${baseY}`;
        const steps = Math.max(Math.floor(Math.abs(length) / 5), 8);
        const stepSize = length / steps;
        
        for (let i = 1; i <= steps; i++) {
            const x = x1 + i * stepSize;
            const prevX = x1 + (i - 1) * stepSize;
            const midX = (prevX + x) / 2;
            const midJitter = Math.sin((x1 + y1 + i * 13) * 0.31) * 0.9;
            const endJitter = Math.cos((x1 + y1 + i * 19) * 0.23) * 0.8;
            const midAmp = amplitude + Math.sin(i * 0.7) * 0.8;
            const endAmp = amplitude + Math.cos(i * 0.6) * 0.7;
            const midY = baseY + midAmp * Math.sin((midX - x1) / length * Math.PI * 5) + midJitter;
            const endY = baseY + endAmp * Math.sin((x - x1) / length * Math.PI * 5) + endJitter;
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
            hasControls: false, hasBorders: false,
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
