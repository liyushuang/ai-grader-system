/**
 * 星星标注 — Fabric.js 轻量版
 * 琥珀金 #F59E0B, 16×16px, 小光晕, 不遮挡文字
 */
class StarAnnotation {
    static create(cx, cy, options = {}) {
        const starColor = '#F59E0B';
        const outerR = 8, innerR = 3.5;
        
        const points = StarAnnotation._getStarPoints(cx, cy, outerR, innerR);
        
        // 小光晕
        const glowPoints = StarAnnotation._getStarPoints(cx, cy, outerR + 2, innerR + 1);
        const glow = new fabric.Polygon(glowPoints, {
            fill: 'rgba(245, 158, 11, 0.2)',
            stroke: '', selectable: false, evented: false, objectCaching: true,
        });

        // 主星星
        const star = new fabric.Polygon(points, {
            fill: starColor, stroke: '#D97706', strokeWidth: 1, objectCaching: true,
        });

        // 小高光
        const highlightPoints = StarAnnotation._getStarPoints(cx, cy, outerR * 0.4, innerR * 0.25);
        const highlight = new fabric.Polygon(highlightPoints, {
            fill: 'rgba(255, 255, 255, 0.25)', stroke: '',
            selectable: false, evented: false, objectCaching: true,
        });

        const group = new fabric.Group([glow, star, highlight], {
            selectable: true, evented: true,
            hasControls: false, hasBorders: true,
            borderColor: starColor, borderScaleFactor: 1,
            padding: 4, lockRotation: true, lockScalingX: true, lockScalingY: true,
            ...options,
        });

        group.annotationType = 'star';
        group._starData = { cx, cy, outerR, innerR };
        group._starPoly = star;
        group._glowPoly = glow;

        return group;
    }

    static _getStarPoints(cx, cy, outerR, innerR) {
        const pts = [];
        for (let i = 0; i < 10; i++) {
            const angle = (i * Math.PI) / 5 - Math.PI / 2;
            const r = i % 2 === 0 ? outerR : innerR;
            pts.push({ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
        }
        return pts;
    }
}
