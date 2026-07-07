/**
 * 批改报告面板 — 展示总分、六维评分（含分析）、总评、优缺点等完整批改信息
 */
class GradingReportPanel {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
    }

    render(gradingData) {
        if (!gradingData || !gradingData.total_score) {
            this.container.innerHTML = '<div class="report-empty">暂无批改数据</div>';
            return;
        }

        const d = gradingData;
        const scoreColor = this._scoreColor(d.total_score);

        this.container.innerHTML = `
            <!-- 总分 -->
            <div class="report-section">
                <div class="report-score" style="color:${scoreColor}">
                    <span class="score-number">${d.total_score}</span>
                    <span class="score-label">/ 100 分</span>
                </div>
                <div class="report-meta">
                    ${d.total_errors ? `<span class="meta-badge error">${d.total_errors} 处错误</span>` : ''}
                    ${d.system_tags ? d.system_tags.map(t => `<span class="meta-badge tag">${t}</span>`).join('') : ''}
                </div>
            </div>

            <!-- 六维评分 + 维度分析 -->
            ${d.dimension_scores ? this._renderDimensions(d.dimension_scores, d.dimension_analysis) : ''}

            <!-- 作业完成情况 -->
            ${d.homework_completion ? `
            <div class="report-section">
                <div class="report-label">📝 完成情况</div>
                <div class="report-text">${d.homework_completion}</div>
            </div>` : ''}

            <!-- 总评 -->
            ${d.overall_comment ? `
            <div class="report-section">
                <div class="report-label">💬 教师总评</div>
                <div class="report-text">${d.overall_comment}</div>
            </div>` : ''}

            <!-- 优点 -->
            ${d.strengths && d.strengths.length ? `
            <div class="report-section">
                <div class="report-label">👍 优点</div>
                <ul class="report-list good">${d.strengths.map(s => `<li>${s}</li>`).join('')}</ul>
            </div>` : ''}

            <!-- 问题 -->
            ${d.weaknesses && d.weaknesses.length ? `
            <div class="report-section">
                <div class="report-label">⚠️ 待改进</div>
                <ul class="report-list warn">${d.weaknesses.map(w => `<li>${w}</li>`).join('')}</ul>
            </div>` : ''}

            <!-- 建议 -->
            ${d.suggestions && d.suggestions.length ? `
            <div class="report-section">
                <div class="report-label">💡 改进建议</div>
                <ul class="report-list tip">${d.suggestions.map(s => `<li>${s}</li>`).join('')}</ul>
            </div>` : ''}

            <!-- 点睛句 -->
            ${d.highlight_sentences && d.highlight_sentences.length ? `
            <div class="report-section">
                <div class="report-label">⭐ 点睛句积累</div>
                <ul class="report-list star">${d.highlight_sentences.map(h => `<li>${h}</li>`).join('')}</ul>
            </div>` : ''}

            <!-- 家长反馈 -->
            ${d.parent_feedback ? `
            <div class="report-section">
                <div class="report-label">👨‍👩‍👧 家长反馈</div>
                <div class="report-text feedback">${d.parent_feedback}</div>
            </div>` : ''}
        `;
    }

    _renderDimensions(dims, analysis) {
        const dimLabels = {
            '完整度': '📋', '准确度': '🎯', '重点词掌握': '📖',
            '句式处理': '🏗️', '表达流畅度': '✨', '忠实原文': '📜'
        };

        let html = '<div class="report-section"><div class="report-label">📊 六维评分</div>';

        for (const [name, score] of Object.entries(dims)) {
            const pct = Math.min(100, Math.max(0, (score / 20) * 100));
            const color = pct >= 80 ? '#52c41a' : pct >= 50 ? '#faad14' : '#ff4d4f';
            const emoji = dimLabels[name] || '•';

            html += `
                <div class="dim-item">
                    <div class="dim-header">
                        <span class="dim-name">${emoji} ${name}</span>
                        <span class="dim-score" style="color:${color}">${score}/20</span>
                    </div>
                    <div class="dim-bar"><div class="dim-fill" style="width:${pct}%;background:${color}"></div></div>`;

            // 维度详细分析
            if (analysis && analysis[name]) {
                const a = analysis[name];
                html += `<div class="dim-analysis">`;
                if (a.strength) {
                    html += `<div class="dim-strength"><span class="dim-tag good">✓ 做得好</span>${a.strength}</div>`;
                }
                if (a.weakness) {
                    html += `<div class="dim-weakness"><span class="dim-tag warn">! 待提高</span>${a.weakness}</div>`;
                }
                html += `</div>`;
            }

            html += `</div>`;
        }
        html += '</div>';
        return html;
    }

    _scoreColor(score) {
        if (score >= 90) return '#52c41a';
        if (score >= 75) return '#faad14';
        if (score >= 60) return '#fa8c16';
        return '#ff4d4f';
    }

    clear() {
        this.container.innerHTML = '<div class="report-empty">暂无批改数据</div>';
    }
}
