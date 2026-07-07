/**
 * 批改报告面板 — 支持总评、详细点评、全文润色子 Tab 切换
 * 包含分数 badges、三种总评风格一键秒级切换、教师评语与家长反馈在线二次编辑、六维雷达表、全文润色及逐句对照。
 */
class GradingReportPanel {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.gradingData = null;
        this._activeSubTab = 'overall'; // 'overall' | 'detail' | 'polishing'
        this._activeCommentStyle = 'general'; // 'general' | 'encouraging' | 'instructive'
    }

    render(gradingData) {
        if (!gradingData) {
            this.container.innerHTML = '<div class="report-empty">暂无批改数据</div>';
            return;
        }

        this.gradingData = gradingData;
        const d = gradingData;

        // Ensure fields exist
        if (!d.overall_comment_general) d.overall_comment_general = d.overall_comment || '';
        if (!d.overall_comment_encouraging) d.overall_comment_encouraging = '';
        if (!d.overall_comment_instructive) d.overall_comment_instructive = '';

        const activeOverall = this._activeSubTab === 'overall' ? 'active' : '';
        const activeDetail = this._activeSubTab === 'detail' ? 'active' : '';
        const activePolishing = this._activeSubTab === 'polishing' ? 'active' : '';

        let html = `
            <!-- 子 Tab 切换栏 -->
            <div class="panel-tabs report-tabs" style="margin: -12px -16px 12px -16px; border-top: 1px solid #e0e0e0; background:#f8fafc; border-bottom:1px solid #e2e8f0;">
                <div class="panel-tab ${activeOverall}" style="padding:10px 4px;font-size:12px;" onclick="window.sidePanel.reportPanel.switchSubTab('overall')">详细点评</div>
                <div class="panel-tab ${activeDetail}" style="padding:10px 4px;font-size:12px;" onclick="window.sidePanel.reportPanel.switchSubTab('detail')">分项分析</div>
                <div class="panel-tab ${activePolishing}" style="padding:10px 4px;font-size:12px;" onclick="window.sidePanel.reportPanel.switchSubTab('polishing')">全文润色</div>
            </div>
            <div class="report-tab-body" style="padding-top:4px;">
        `;

        if (this._activeSubTab === 'overall') {
            // ── Tab 1: 可交付详细点评 ──
            const score = d.total_score || 0;
            let ratingLevel = '优';
            if (score < 60) ratingLevel = '差';
            else if (score < 75) ratingLevel = '中';
            else if (score < 90) ratingLevel = '良';

            html += `
                <div class="report-score-box" style="padding:10px 0 12px;margin-bottom:12px;">
                    <div class="report-score" style="color:${this._scoreColor(score)}; padding:0; text-align:left;">
                        <span class="score-number" style="font-size:34px;">${score}</span>
                        <span class="score-label" style="font-size:12px;color:#94a3b8;margin-left:4px;">/ 100 分</span>
                    </div>
                    <span class="rating-badge level-${ratingLevel}" style="margin-left:auto;">${ratingLevel}级</span>
                </div>
                <div class="report-copy-row">
                    <button class="copy-btn" onclick="window.sidePanel.reportPanel.copyBlock('all')">复制全部</button>
                    <button class="copy-btn" onclick="window.sidePanel.reportPanel.copyBlock('correction')">复制订正</button>
                    <button class="copy-btn" onclick="window.sidePanel.reportPanel.copyBlock('parent')">复制家长反馈</button>
                </div>
                ${this._renderDeliverableSections(d)}
                <button class="edit-btn save" style="width:100%; height:38px; font-weight:600; margin-top:12px; border-radius:8px; background:#2563eb;" onclick="window.sidePanel.reportPanel.saveReportChanges()">保存点评与标注</button>
            `;
        } else if (this._activeSubTab === 'detail') {
            // ── Tab 2: 详细点评 ──
            html += `
                <div class="report-label" style="margin-top:4px;">教师总评</div>
                <div class="style-switcher">
                    <button class="style-btn ${this._activeCommentStyle === 'general' ? 'active' : ''}" onclick="window.sidePanel.reportPanel.switchCommentStyle('general')">通用</button>
                    <button class="style-btn ${this._activeCommentStyle === 'encouraging' ? 'active' : ''}" onclick="window.sidePanel.reportPanel.switchCommentStyle('encouraging')">鼓励</button>
                    <button class="style-btn ${this._activeCommentStyle === 'instructive' ? 'active' : ''}" onclick="window.sidePanel.reportPanel.switchCommentStyle('instructive')">指导</button>
                </div>
                <textarea class="textarea-editable" id="teacherCommentText" placeholder="在此输入教师评语...">${this.getActiveCommentText()}</textarea>
            `;
            html += d.dimension_scores ? this._renderDimensions(d.dimension_scores, d.dimension_analysis) : '';
            html += d.homework_completion ? `
                <div class="report-section">
                    <div class="report-label">📝 完成情况</div>
                    <div class="report-text">${d.homework_completion}</div>
                </div>` : '';
            html += d.strengths && d.strengths.length ? `
                <div class="report-section">
                    <div class="report-label">👍 优点</div>
                    <ul class="report-list good">${d.strengths.map(s => `<li>${s}</li>`).join('')}</ul>
                </div>` : '';
            html += d.weaknesses && d.weaknesses.length ? `
                <div class="report-section">
                    <div class="report-label">⚠️ 待改进</div>
                    <ul class="report-list warn">${d.weaknesses.map(w => `<li>${w}</li>`).join('')}</ul>
                </div>` : '';
            html += d.suggestions && d.suggestions.length ? `
                <div class="report-section">
                    <div class="report-label">💡 改进建议</div>
                    <ul class="report-list tip">${d.suggestions.map(s => `<li>${s}</li>`).join('')}</ul>
                </div>` : '';
        } else if (this._activeSubTab === 'polishing') {
            // ── Tab 3: 全文润色 ──
            html += `
                <div class="report-section">
                    <div class="report-label">✨ 连贯全文润色</div>
                    <div class="polished-box">${d.polished_full_translation || '暂无连贯全文润色。'}</div>
                </div>
                
                <div class="report-section">
                    <div class="report-label">🔍 逐句对照与细节润色</div>
                    <div class="comparison-list">
            `;
            
            if (d.sentence_analyses && d.sentence_analyses.length) {
                d.sentence_analyses.forEach((sa, idx) => {
                    const errsHtml = sa.errors && sa.errors.length 
                        ? `<div class="comp-errs">
                             <strong>问题：</strong>${sa.errors.map(e => `[${e.error_type}] "${e.original_text}" → "${e.correct_text}" (${e.reason})`).join('; ')}
                           </div>`
                        : '';
                        
                    html += `
                        <div class="comparison-item" style="padding:10px 0; border-bottom:1px solid #f1f5f9;">
                            <span class="comp-lbl">第 ${idx + 1} 句原文</span>
                            <div class="comp-val original" style="color:#64748b; font-weight:500;">${sa.original_classical}</div>
                            <span class="comp-lbl">学生翻译</span>
                            <div class="comp-val student" style="color:#334155;">${sa.student_translation || '(未识别)'}</div>
                            <span class="comp-lbl">润色译文</span>
                            <div class="comp-val polished" style="color:#10b981; background:#f0fdf4; padding:4px 6px; border-radius:4px; font-weight:500;">${sa.polished_translation || sa.standard_translation}</div>
                            ${errsHtml}
                        </div>
                    `;
                });
            } else {
                html += '<div style="color:#999;font-size:12px;text-align:center;padding:12px;">暂无句段对照数据</div>';
            }
            
            html += `
                    </div>
                </div>
            `;
        }

        html += `</div>`;
        this.container.innerHTML = html;

        // Setup event listeners for textareas to sync updates
        const commentArea = document.getElementById('teacherCommentText');
        if (commentArea) {
            commentArea.addEventListener('input', (e) => {
                const val = e.target.value;
                if (this._activeCommentStyle === 'general') {
                    d.overall_comment_general = val;
                    d.overall_comment = val;
                } else if (this._activeCommentStyle === 'encouraging') {
                    d.overall_comment_encouraging = val;
                } else if (this._activeCommentStyle === 'instructive') {
                    d.overall_comment_instructive = val;
                }
            });
        }
        
        const feedbackArea = document.getElementById('parentFeedbackText');
        if (feedbackArea) {
            feedbackArea.addEventListener('input', (e) => {
                d.parent_feedback = e.target.value;
            });
        }
    }

    _renderDeliverableSections(d) {
        const annotations = window.annotationStore ? window.annotationStore.getAll() : (d.annotations || []);
        const lineItems = annotations.filter(a => a.type === 'line');
        const circleItems = annotations.filter(a => a.type === 'circle');
        const wavyItems = annotations.filter(a => a.type === 'wavy');
        const starItems = annotations.filter(a => a.type === 'star');
        const correctionItems = [...lineItems, ...circleItems];
        const errorItems = correctionItems.length ? [] : this._collectErrors(d);

        const summary = this.getActiveCommentText() || d.homework_completion || '本次作业整体完成较认真，可以继续围绕准确翻译和表达通顺两点改进。';
        const corrections = [
            ...correctionItems.map((a, idx) => `${idx + 1}. ${a.comment || '这处需要重新订正，注意和原文逐字对应。'}`),
            ...errorItems.map((e, idx) => `${correctionItems.length + idx + 1}. ${e}`)
        ].slice(0, 6);
        const strengths = [
            ...wavyItems.map(a => a.comment || '这句翻译比较准确、流畅，可以保留这种表达。'),
            ...starItems.map(a => a.comment || '这处是文章理解的关键句，建议重点记忆。'),
            ...(d.strengths || [])
        ].slice(0, 5);
        const pitfalls = [
            ...(d.weaknesses || []),
            ...(d.suggestions || [])
        ].slice(0, 5);

        return `
            <section class="deliverable-section" data-copy-block="summary">
                <div class="deliverable-head">
                    <span>详细点评</span>
                    <button class="copy-link" onclick="window.sidePanel.reportPanel.copyBlock('summary')">复制</button>
                </div>
                <textarea class="textarea-editable deliverable-textarea" id="teacherCommentText" placeholder="输入详细点评...">${this._escapeHtml(summary)}</textarea>
            </section>

            <section class="deliverable-section" data-copy-block="correction">
                <div class="deliverable-head">
                    <span>订正建议</span>
                    <button class="copy-link" onclick="window.sidePanel.reportPanel.copyBlock('correction')">复制</button>
                </div>
                ${this._renderBulletList(corrections, '暂无明确订正项，可根据图中红线位置补充。')}
            </section>

            <section class="deliverable-section" data-copy-block="strengths">
                <div class="deliverable-head">
                    <span>优秀表达</span>
                    <button class="copy-link" onclick="window.sidePanel.reportPanel.copyBlock('strengths')">复制</button>
                </div>
                ${this._renderBulletList(strengths, '暂无优秀表达记录，可从波浪线或星标处补充。')}
            </section>

            <section class="deliverable-section" data-copy-block="pitfalls">
                <div class="deliverable-head">
                    <span>易错点</span>
                    <button class="copy-link" onclick="window.sidePanel.reportPanel.copyBlock('pitfalls')">复制</button>
                </div>
                ${this._renderBulletList(pitfalls, '暂无易错点记录。')}
            </section>

            <section class="deliverable-section" data-copy-block="parent">
                <div class="deliverable-head">
                    <span>家长反馈</span>
                    <button class="copy-link" onclick="window.sidePanel.reportPanel.copyBlock('parent')">复制</button>
                </div>
                <textarea class="textarea-editable deliverable-textarea parent" id="parentFeedbackText" placeholder="输入家长反馈...">${this._escapeHtml(d.parent_feedback || '')}</textarea>
            </section>
        `;
    }

    _renderBulletList(items, emptyText) {
        const clean = (items || []).filter(Boolean);
        if (!clean.length) {
            return `<div class="deliverable-empty">${emptyText}</div>`;
        }
        return `<ul class="deliverable-list">${clean.map(item => `<li>${this._escapeHtml(item)}</li>`).join('')}</ul>`;
    }

    _collectErrors(d) {
        const out = [];
        (d.sentence_analyses || []).forEach(sa => {
            (sa.errors || []).forEach(e => {
                const original = e.original_text || e.error_text || '';
                const correct = e.correct_text || '';
                const reason = e.reason || e.error_type || '';
                if (original || correct || reason) {
                    out.push(`${original}${correct ? ` → ${correct}` : ''}${reason ? `：${reason}` : ''}`);
                }
            });
        });
        return out;
    }

    async copyBlock(block) {
        const root = this.container;
        const nodes = block === 'all'
            ? Array.from(root.querySelectorAll('[data-copy-block]'))
            : Array.from(root.querySelectorAll(`[data-copy-block="${block}"]`));
        const text = nodes.map(node => {
            const title = node.querySelector('.deliverable-head span')?.textContent?.trim() || '';
            const textarea = node.querySelector('textarea');
            const body = textarea
                ? textarea.value.trim()
                : Array.from(node.querySelectorAll('li')).map(li => li.textContent.trim()).join('\n');
            return [title, body].filter(Boolean).join('\n');
        }).filter(Boolean).join('\n\n');

        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            if (typeof showToast === 'function') showToast('已复制');
        } catch (e) {
            const tmp = document.createElement('textarea');
            tmp.value = text;
            document.body.appendChild(tmp);
            tmp.select();
            document.execCommand('copy');
            document.body.removeChild(tmp);
            if (typeof showToast === 'function') showToast('已复制');
        }
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    switchSubTab(subTab) {
        this._activeSubTab = subTab;
        this.render(this.gradingData);
    }

    switchCommentStyle(style) {
        this._activeCommentStyle = style;
        this.render(this.gradingData);
    }

    getActiveCommentText() {
        const d = this.gradingData;
        if (!d) return '';
        if (this._activeCommentStyle === 'general') {
            return d.overall_comment_general || d.overall_comment || '';
        } else if (this._activeCommentStyle === 'encouraging') {
            return d.overall_comment_encouraging || '';
        } else if (this._activeCommentStyle === 'instructive') {
            return d.overall_comment_instructive || '';
        }
        return '';
    }

    async saveReportChanges() {
        if (!this.gradingData) return;
        
        if (typeof currentImageIndex !== 'undefined' && imageSessions[currentImageIndex]) {
            imageSessions[currentImageIndex].gradingData = this.gradingData;
        }

        const tid = (typeof currentImageIndex !== 'undefined' && imageSessions[currentImageIndex]) 
            ? imageSessions[currentImageIndex].taskId 
            : ('task_' + Date.now());
            
        const fileName = (typeof currentImageIndex !== 'undefined' && imageSessions[currentImageIndex])
            ? imageSessions[currentImageIndex].fileName
            : '';
            
        const annotations = window.annotationStore.toJSON();
        
        try {
            const resp = await fetch('/api/annotations/' + tid, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    annotations: annotations,
                    gradingData: this.gradingData,
                    fileName: fileName
                }),
            });
            const result = await resp.json();
            if (result.ok) {
                if (typeof showToast === 'function') {
                    showToast('✅ 报告与标注修改已成功保存');
                } else {
                    alert('报告与标注修改已成功保存');
                }
            }
        } catch (e) {
            if (typeof showToast === 'function') {
                showToast('❌ 保存报告失败: ' + e.message);
            } else {
                alert('保存报告失败: ' + e.message);
            }
        }
    }

    _renderDimensions(dims, analysis) {
        const dimLabels = {
            '完整度': '📋', '准确度': '🎯', '重点词掌握': '📖',
            '句式处理': '🏗️', '表达流畅度': '✨', '忠实原文': '📜'
        };

        let html = '<div class="report-section"><div class="report-label">📊 六维评分</div>';

        for (const [name, rawScore] of Object.entries(dims)) {
            const score = Math.min(20, Math.max(0, Number(rawScore) || 0));
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
