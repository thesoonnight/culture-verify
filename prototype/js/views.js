/* 视图模板：不直接改状态，只负责把 state 渲染成 HTML。 */
window.CV = window.CV || {};
(function (CV) {
  'use strict';

  const { esc, fmtPct, fmtSec } = CV.utils;
  const M = CV.model;
  const store = CV.store;

  const ctx = () => ({ source: store.state.source, dataset: store.state.dataset.name });
  const img = (task, side) => M.imageUrl(task, side, ctx());

  /* --------------------------------------------------------------- 公共块 */
  function headHTML(task, list) {
    const chips =
      task.mode === 'pointwise'
        ? `<span class="chip">${esc(task.axis || '未标注轴')}</span>
           <span class="chip">${esc(task.lang || '未标注语言')}</span>
           ${task.region ? `<span class="chip ghost">${esc(task.region)}</span>` : ''}`
        : `<span class="chip">${esc(task.axis || '未标注轴')}</span>
           <span class="chip">${esc(task.lang || '未标注语言')}</span>`;
    return `<div class="view-head">
      <div class="crumbs">
        <span class="sample-id">${esc(task.id)}</span>
        ${chips}
        <span class="chip ghost">盲评 · 不显示模型</span>
      </div>
      ${pagerHTML(list)}
    </div>`;
  }

  function pagerHTML(list) {
    const { idx, annotations } = store.state;
    return `<div class="pager">${list
      .map((task, i) => {
        const ann = annotations[M.taskKey(task)];
        const status = (ann && ann.status) || 'todo';
        const cls = [
          'dot',
          status === 'done' ? 'done' : '',
          status === 'flagged' ? 'flagged' : '',
          status === 'skipped' ? 'skipped' : '',
          status === 'doing' ? 'doing' : '',
          i === idx ? 'current' : '',
        ]
          .filter(Boolean)
          .join(' ');
        return `<button class="${cls}" data-jump="${i}" title="${esc(task.id)} · ${status}" aria-label="跳到 ${esc(task.id)}"></button>`;
      })
      .join('')}</div>`;
  }

  function stageHTML(src, alt) {
    return `<div class="stage" data-zoom-stage>
      <div class="zoom-layer"><img src="${esc(src)}" alt="${esc(alt)}" draggable="false"></div>
      <div class="stage-tools">
        <button class="tool" data-act="zoom-out" title="缩小">−</button>
        <button class="tool" data-act="zoom-in" title="放大">＋</button>
        <button class="tool" data-act="zoom-fit" title="适应窗口">适应</button>
        <button class="tool" data-act="zoom-full" title="原始像素">1:1</button>
        <button class="tool" data-act="lightbox" title="看大图">⤢</button>
      </div>
    </div>`;
  }

  function pointItemHTML(task, item, index, ann) {
    const { config } = store.state;
    const verdict = ann.verdicts[item.dim];
    const cls = verdict ? (verdict.agree ? 'is-agree' : 'is-disagree') : '';
    const label = item.label || M.labelFor(config, item.dim, item.dim);
    const question = item.question || M.questionFor(config, item.dim);
    const rationale =
      item.rationale && config.showRationale
        ? `<p class="rationale"><b>AI 理由</b> ${esc(item.rationale)}</p>`
        : '';
    return `<div class="eval-item ${cls}" data-dim="${esc(item.dim)}">
      <div class="eval-top">
        <span class="idx">${index + 1}</span>
        <span class="dim-label" data-dim-label="${esc(item.dim)}">${esc(label)}</span>
        <span class="score score-${item.score}">AI：${item.score === 1 ? '对' : '错'}</span>
      </div>
      <p class="eval-q">${esc(question)}</p>
      <div class="eval-controls">
        <button class="vbtn yes ${verdict && verdict.agree ? 'active' : ''}" data-vote="1" aria-pressed="${!!(verdict && verdict.agree)}">
          <span class="vicon">✓</span>同意
        </button>
        <button class="vbtn no ${verdict && verdict.agree === false ? 'active' : ''}" data-vote="0" aria-pressed="${!!(verdict && verdict.agree === false)}">
          <span class="vicon">✗</span>不同意
        </button>
      </div>
      ${rationale}
      ${correctionHTML(item.dim, verdict)}
    </div>`;
  }

  function correctionHTML(id, verdict) {
    const show = verdict && verdict.agree === false;
    const current = verdict && verdict.correction;
    const btn = (value, text) =>
      `<button class="chip-btn ${current === value ? 'active' : ''}" data-corr="${value}">${text}</button>`;
    return `<div class="correction ${show ? 'show' : ''}" data-correction="${esc(id)}">
      <span class="corr-label">实际应为</span>
      ${btn('1', '1')}${btn('0', '0')}${btn('?', '不确定')}
      <span class="corr-hint">可选</span>
    </div>`;
  }

  function pairStageHTML(src, label, alt) {
    return `<div class="stage pair-stage" data-zoom-stage>
      <span class="fig-label">${label}</span>
      <div class="zoom-layer"><img src="${esc(src)}" alt="${esc(alt)}" draggable="false"></div>
      <div class="stage-tools">
        <button class="tool" data-act="zoom-out" title="缩小">−</button>
        <button class="tool" data-act="zoom-in" title="放大">＋</button>
        <button class="tool" data-act="lightbox" title="看大图">⤢</button>
      </div>
    </div>`;
  }

  /* ---------------------------------------------------------------- 单图 */
  function pointwiseView(task) {
    const list = store.tasksFor('pointwise');
    const ann = store.ensureAnn(task);
    store.touchTask(task);
    return `${headHTML(task, list)}
      <div class="layout">
        <section class="stage-col">${stageHTML(img(task), task.prompt)}</section>
        <aside class="side">
          <div class="card prompt-card">
            <div class="card-label">Prompt · ${esc(task.lang || '未标注')}</div>
            <p class="prompt-text">${esc(task.prompt)}</p>
            ${
              task.attrs && task.attrs.length
                ? `<div class="attrs">
                     <div class="attrs-label">期望文化属性</div>
                     <ul>${task.attrs.map((attr) => `<li>${esc(attr)}</li>`).join('')}</ul>
                   </div>`
                : ''
            }
          </div>
          <div class="card eval-card">
            <div class="card-head">
              <span>AI判断</span>
              <span class="muted">逐项 · ${task.items.length} 项判断</span>
            </div>
            ${task.items.map((item, i) => pointItemHTML(task, item, i, ann)).join('')}
          </div>
        </aside>
      </div>`;
  }

  /* ---------------------------------------------------------------- 双图 */
  function pairRowHTML(task, crit, index, order, ann) {
    const { config } = store.state;
    const verdict = ann.verdicts[crit.id];
    const a = Number(task.scores.A[crit.id]);
    const b = Number(task.scores.B[crit.id]);
    const s1 = order === 'AB' ? a : b;
    const s2 = order === 'AB' ? b : a;
    const pref = s1 === s2 ? 'tie' : s1 > s2 ? '1' : '2';
    const label = crit.label || M.labelFor(config, crit.id, crit.id);
    const question = crit.question || M.questionFor(config, crit.id);
    const cls = verdict ? (verdict.agree ? 'is-agree' : 'is-disagree') : '';
    return `<tr class="crit-row ${cls}" data-crit="${esc(crit.id)}">
      <td>
        <div class="crit-cell">
          <span class="idx">${index + 1}</span>
          <div><b data-crit-label="${esc(crit.id)}">${esc(label)}</b><small>${esc(question)}</small></div>
        </div>
      </td>
      <td class="num ${s1 > s2 ? 'hi' : ''}">${s1}</td>
      <td class="num ${s2 > s1 ? 'hi' : ''}">${s2}</td>
      <td class="conclusion">${pref === 'tie' ? '持平' : `图 ${pref} 更好`}<span class="delta">Δ${Math.abs(s1 - s2)}</span></td>
      <td class="vote-cell">
        <div class="verdict compact">
          <button class="vbtn yes ${verdict && verdict.agree ? 'active' : ''}" data-vote="1" aria-pressed="${!!(verdict && verdict.agree)}" title="同意（${index + 1}）">✓</button>
          <button class="vbtn no ${verdict && verdict.agree === false ? 'active' : ''}" data-vote="0" aria-pressed="${!!(verdict && verdict.agree === false)}" title="不同意（⇧${index + 1}）">✗</button>
        </div>
        ${pairCorrectionHTML(crit.id, order, verdict)}
      </td>
    </tr>`;
  }

  function pairCorrectionHTML(id, order, verdict) {
    const show = verdict && verdict.agree === false;
    const current = verdict && verdict.correction;
    const options = [
      ['A', `图 ${order === 'AB' ? 1 : 2} 更好`],
      ['B', `图 ${order === 'AB' ? 2 : 1} 更好`],
      ['tie', '差不多'],
      ['gap', '方向对但分差过大'],
    ];
    return `<div class="corr-select-wrap ${show ? 'show' : ''}">
      <select class="corr-select" data-corr-select="${esc(id)}" aria-label="实际应为">
        <option value="">实际应为…</option>
        ${options
          .map(
            ([value, text]) =>
              `<option value="${value}" ${current === value ? 'selected' : ''}>${text}</option>`
          )
          .join('')}
      </select>
    </div>`;
  }

  function pairwiseView(task) {
    const list = store.tasksFor('pairwise');
    const ann = store.ensureAnn(task);
    store.touchTask(task);
    const order = ann.shown_as || M.randomOrder(task.id, store.state.annotator);
    const src1 = order === 'AB' ? img(task, 'A') : img(task, 'B');
    const src2 = order === 'AB' ? img(task, 'B') : img(task, 'A');
    return `${headHTML(task, list)}
      <div class="pair-wrap">
        <div class="card prompt-bar">
          <div class="card-label">Prompt · ${esc(task.lang || '未标注')}</div>
          <p class="prompt-text">${esc(task.prompt)}</p>
        </div>
        <div class="pair-grid">
          ${pairStageHTML(src1, '图 1', task.prompt)}
          ${pairStageHTML(src2, '图 2', task.prompt)}
        </div>
        <div class="pair-tools">
          <span>同步缩放：滚轮 / 拖拽 · 双击复位</span>
          <div class="spacer"></div>
          <button class="tool" data-act="zoom-fit">适应</button>
          <button class="tool" data-act="zoom-full">1:1</button>
          <button class="tool" data-act="swap">⇄ 交换左右</button>
        </div>
        <div class="card score-card">
          <div class="score-head">
            <div><strong>画面质感对比</strong><span class="muted">核对 AI 的分数与结论</span></div>
            <span class="chip ghost">分数 0–10</span>
          </div>
          <table class="score-table">
            <thead><tr><th>维度</th><th>图 1</th><th>图 2</th><th>AI结论</th><th>人工核验</th></tr></thead>
            <tbody>${task.criteria.map((crit, i) => pairRowHTML(task, crit, i, order, ann)).join('')}</tbody>
          </table>
          ${task.note ? `<div class="eval-note">${esc(task.note)}</div>` : ''}
          <div class="overall">
            <span>你的整体偏好（可选）</span>
            <div class="seg">
              <button class="seg-btn ${ann.overall === 'A' ? 'active' : ''}" data-overall="A">图 ${order === 'AB' ? 1 : 2}</button>
              <button class="seg-btn ${ann.overall === 'tie' ? 'active' : ''}" data-overall="tie">平局</button>
              <button class="seg-btn ${ann.overall === 'B' ? 'active' : ''}" data-overall="B">图 ${order === 'AB' ? 2 : 1}</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  /* -------------------------------------------------------------- 操作栏 */
  function actionbarHTML(task) {
    const ann = store.ensureAnn(task);
    const hint =
      task.mode === 'pointwise'
        ? '键盘 1/2/3 同意 · Shift+1/2/3 不同意 · Enter 下一题'
        : '键盘 1/2 同意 · Shift+1/2 不同意 · Enter 下一题';
    return `<div class="actionbar-inner">
      <div class="note-wrap">
        <span class="note-icon">✎</span>
        <input class="note-input" id="noteInput" placeholder="备注（可选）" value="${esc(ann.note || '')}">
      </div>
      <span class="hint">${hint}</span>
      <div class="spacer"></div>
      <button class="btn ghost ${ann.status === 'flagged' ? 'warn' : ''}" data-act="flag">待议 <kbd>F</kbd></button>
      <button class="btn ghost" data-act="skip">跳过 <kbd>S</kbd></button>
      <button class="btn" data-act="prev">上一题 <kbd>←</kbd></button>
      <button class="btn primary" data-act="next">下一题 <kbd>⏎</kbd></button>
    </div>`;
  }

  /* ---------------------------------------------------------------- 汇总 */
  function summaryHTML(summary) {
    const state = store.state;
    if (state.summaryLoading) {
      return `<section class="summary"><div class="empty-card"><div class="loading-ring"></div><p>正在计算一致性…</p></div></section>`;
    }
    if (!summary) {
      return `<section class="summary"><div class="empty-card"><p>还没有汇总数据。</p><button class="btn" data-act="back">返回核验</button></div></section>`;
    }
    const overall = summary.overall || {};
    const annotatedTasks =
      summary.annotated_tasks != null
        ? summary.annotated_tasks
        : state.tasks.filter((task) => store.isDone(task)).length;
    const dims = [...(summary.dimensions || []), ...(summary.criteria || [])];
    const bars = dims.length
      ? dims
          .map((item) => {
            const rate = item.agreement_rate || 0;
            return `<div class="bar-row">
              <div class="name"><b>${esc(item.label)}</b>${item.scope === 'pointwise' ? '单图判定项' : '双图评分维度'}</div>
              <div class="bar"><div class="bar-fill" style="width:${(rate * 100).toFixed(1)}%"></div></div>
              <div class="rate">${item.n ? fmtPct(item.agreement_rate) : '—'} <span>${item.agree}/${item.n}</span></div>
            </div>`;
          })
          .join('')
      : '<div class="dis-item" style="color:var(--faint)">还没有判定记录</div>';

    let rawSum = 0;
    let rawN = 0;
    let truthSum = 0;
    let truthN = 0;
    (summary.dimensions || []).forEach((item) => {
      if (item.n) {
        rawSum += (item.raw_pass_rate || 0) * item.n;
        rawN += item.n;
      }
      if (item.truth_n) {
        truthSum += (item.verified_pass_rate || 0) * item.truth_n;
        truthN += item.truth_n;
      }
    });
    const rawRate = rawN ? rawSum / rawN : null;
    const verifiedRate = truthN ? truthSum / truthN : null;
    const delta = rawN && truthN ? Math.round((verifiedRate - rawRate) * 100) : null;

    const annotators = summary.annotators || [];
    const inter = summary.inter_annotator || {};
    const interBlock = annotators.length >= 2
      ? `<div class="inter-grid">
           <div><span>双人一致率</span><b>${fmtPct(inter.percent_agreement)}</b></div>
           <div><span>Cohen's κ</span><b>${inter.kappa == null ? '—' : inter.kappa.toFixed(2)}</b></div>
           <div><span>重叠判定</span><b>${inter.n_comparisons || 0}</b></div>
           <div><span>标注员</span><b>${annotators.length}</b></div>
         </div>`
      : `<div class="inter-grid single">
           <div><span>标注员</span><b>${annotators.length || 1}</b></div>
           <div class="inter-hint">同一题由 2 位以上标注员完成后，这里会显示 Cohen's κ；当前只有 ${esc(annotators[0] || '本地')}。</div>
         </div>`;

    const byModel = (summary.by_model || []).length
      ? `<div class="card" style="margin-bottom:14px">
           <div class="card-head"><span>按模型的单图通过率</span><span class="muted">raw → verified</span></div>
           <table class="score-table model-table">
             <thead><tr><th>模型</th><th>判定数</th><th>一致率</th><th>原始通过率</th><th>修正后</th></tr></thead>
             <tbody>${summary.by_model
               .map(
                 (row) => `<tr>
                   <td>${esc(row.model)}</td>
                   <td>${row.n}</td>
                   <td>${fmtPct(row.agreement_rate)}</td>
                   <td>${fmtPct(row.raw_pass_rate)}</td>
                   <td>${fmtPct(row.verified_pass_rate)}</td>
                 </tr>`
               )
               .join('')}</tbody>
           </table>
         </div>`
      : '';

    const disagreements = summary.disagreements || [];
    const dis = disagreements.length
      ? disagreements
          .slice(0, 12)
          .map(
            (row) => `<div class="dis-item">
              <span class="bad-id">${esc(row.task_id)}</span>
              <span class="bad-dim">${esc(row.label)}</span>
              <span class="bad-prompt">${esc(row.prompt)}</span>
              <span class="bad-annotator">${esc(row.annotator || '')}</span>
              <button class="btn ghost" data-act="jump-task" data-task="${esc(row.task_id)}">回到该题</button>
            </div>`
          )
          .join('')
      : '<div class="dis-item" style="color:var(--faint)">还没有 ✗ 记录</div>';

    return `<section class="summary">
      <div class="sum-head">
        <h1>核验结果</h1>
        <p>${esc(state.dataset.title || state.dataset.name || '数据集')} · ${
          state.source === 'server' ? '服务器数据' : '本地数据'
        } · 可导出人工评分与一致性报告</p>
      </div>
      <div class="stat-grid">
        <div class="stat-card"><div class="label">已核验题目</div><div class="big">${annotatedTasks}<small> / ${state.tasks.length}</small></div></div>
        <div class="stat-card"><div class="label">判定总数</div><div class="big">${overall.n || 0}<small> 项</small></div></div>
        <div class="stat-card"><div class="label">AI一致率</div><div class="big">${fmtPct(overall.agreement_rate)}</div></div>
        <div class="stat-card"><div class="label">平均每题</div><div class="big">${fmtSec(overall.avg_duration_ms)}</div></div>
      </div>
      <div class="card" style="margin-bottom:14px">
        <div class="card-head"><span>AI 与人工的一致率</span><span class="muted">✓ 同意 / 判定总数</span></div>
        ${bars}
      </div>
      <div class="card" style="margin-bottom:14px">
        <div class="card-head"><span>分数口径：原始 vs 修正后</span><span class="muted">单图判定项 · 通过率</span></div>
        <div class="score-compare">
          <div class="sc-cell"><span>AI原始</span><b>${fmtPct(rawRate)}</b></div>
          <div class="sc-arrow">→</div>
          <div class="sc-cell"><span>人工修正后</span><b class="${verifiedRate != null && verifiedRate < rawRate ? 'down' : 'up'}">${fmtPct(verifiedRate)}</b></div>
          <div class="sc-note">${delta == null ? '还没有单图判定' : `${delta >= 0 ? '+' : '−'}${Math.abs(delta)} pt · ${truthN} 项有真值`}</div>
        </div>
      </div>
      <div class="card" style="margin-bottom:14px">
        <div class="card-head"><span>标注员一致性</span><span class="muted">Cohen's κ</span></div>
        ${interBlock}
      </div>
      ${byModel}
      <div class="card">
        <div class="card-head"><span>分歧清单</span><span class="muted">${disagreements.length} 条</span></div>
        <div class="dis-list">${dis}</div>
      </div>
      <div class="sum-actions">
        <button class="btn primary" data-act="export-verdicts">导出人工评分 CSV</button>
        <button class="btn ghost" data-act="export-consistency">一致性报告 CSV</button>
        <button class="btn ghost" data-act="export-summary">汇总 JSON</button>
        <button class="btn ghost" data-act="back">返回核验</button>
        ${
          state.source === 'local'
            ? '<button class="btn ghost" data-act="reset">清空本地数据</button>'
            : ''
        }
      </div>
    </section>`;
  }

  /* -------------------------------------------------------------- 空状态 */
  function emptyHTML() {
    return `<section class="summary"><div class="empty-card">
      <div class="empty-mark">文</div>
      <h1>还没有数据集</h1>
      <p>把你的评分集和图片打成 zip 导进来，或在终端执行：</p>
      <pre class="code-block">python server.py import --name culture-v1 --tasks tasks.jsonl --images ./images</pre>
      <div class="sum-actions" style="justify-content:center">
        <button class="btn primary" data-act="import">导入数据集</button>
        <button class="btn ghost" data-act="help">看格式说明</button>
      </div>
    </div></section>`;
  }

  /* ---------------------------------------------------------------- 设置 */
  function dimensionEntries(scope) {
    const { config, tasks } = store.state;
    const ids = [];
    tasks.forEach((task) => {
      const list = scope === 'pointwise' ? task.items : task.criteria;
      if (!list) return;
      list.forEach((item) => {
        const id = scope === 'pointwise' ? item.dim : item.id;
        if (id && !ids.includes(id)) ids.push(id);
      });
    });
    if (!ids.length) {
      (scope === 'pointwise' ? CV.config.DEFAULT_DIMENSIONS : CV.config.DEFAULT_CRITERIA).forEach(
        (item) => ids.push(item.id)
      );
    }
    return ids.map((id) => ({
      id,
      label: config.labels[id] || id,
      question: config.questions[id] || '',
    }));
  }

  function settingsHTML() {
    const state = store.state;
    const point = dimensionEntries('pointwise');
    const pair = dimensionEntries('pairwise');
    const toggle = (key, title, desc) => `<div class="toggle-row">
      <div>${title}<small>${desc}</small></div>
      <label class="switch"><input type="checkbox" data-toggle="${key}" ${state.config[key] ? 'checked' : ''}><i></i></label>
    </div>`;
    const field = (scope, item) => `<div class="field">
      <label>${esc(item.id)} · 名称</label>
      <input class="text-input" data-label-input="${esc(item.id)}" value="${esc(item.label)}" placeholder="维度名称">
      <div style="height:6px"></div>
      <input class="text-input" data-question-input="${esc(item.id)}" value="${esc(item.question)}" placeholder="判断说明（显示在项下）">
    </div>`;

    return `<div class="drawer-head">
      <h2>设置</h2>
      <button class="btn ghost icon-only" data-act="close-drawer">✕</button>
    </div>
    <div class="drawer-body">
      <div class="section-label">数据集</div>
      <div class="meta-grid">
        <div><span>名称</span><b>${esc(state.dataset.name || '—')}</b></div>
        <div><span>题目</span><b>${state.tasks.length}</b></div>
        <div><span>来源</span><b>${state.source === 'server' ? '服务器' : '本地演示'}</b></div>
      </div>
      <div class="field" style="margin-top:12px">
        <label>标注员</label>
        <div class="inline-field">
          <input class="text-input" id="annotatorInput" value="${esc(state.annotator)}" placeholder="你的名字" ${state.source === 'local' ? 'disabled' : ''}>
          <button class="btn ghost" data-act="switch-annotator" ${state.source === 'local' ? 'disabled' : ''}>切换</button>
        </div>
        <small class="field-hint">${state.source === 'server' ? '切换后会加载该标注员自己的标注。' : '本地演示模式只有一位标注员。'}</small>
      </div>

      <div class="section-label" style="margin-top:22px">单图核验 · 判定项</div>
      ${point.map((item) => field('pointwise', item)).join('')}
      <div class="section-label" style="margin-top:22px">双图对比 · 评分维度</div>
      ${pair.map((item) => field('pairwise', item)).join('')}

      <div class="section-label" style="margin-top:22px">标注习惯</div>
      ${toggle('showRationale', '显示 AI 理由', '关闭后只看分数，适合盲评')}
      ${toggle('autoNext', '答完自动跳下一题', '所有项都打勾/打叉后自动前进')}
      ${toggle('requireCorrection', '✗ 时必须填「实际应为」', '用于产出修正后的 verified 分数')}
      <p class="field-hint" style="margin-top:10px">维度名称会写回数据集配置（服务器模式）或本地存储。</p>
    </div>
    <div class="drawer-foot">
      <button class="btn ghost" data-act="restore-labels">恢复默认名称</button>
      <div class="spacer"></div>
      <button class="btn primary" data-act="close-drawer">完成</button>
    </div>`;
  }

  /* -------------------------------------------------------------- 帮助 */
  function helpHTML() {
    return `<div class="modal">
      <h2>快捷键与数据说明</h2>
      <p class="sub">${store.state.source === 'server' ? '服务器模式：标注实时保存到数据目录' : '本地演示模式：数据存在浏览器 localStorage'}</p>
      <table class="help-table">
        <tr><td><kbd>1</kbd> … <kbd>9</kbd></td><td>第 N 项同意 AI 判断</td></tr>
        <tr><td><kbd>Shift</kbd> + <kbd>1</kbd> … <kbd>9</kbd></td><td>第 N 项不同意 AI 判断</td></tr>
        <tr><td><kbd>⏎</kbd> / <kbd>→</kbd></td><td>下一题（未答完会提示）</td></tr>
        <tr><td><kbd>←</kbd></td><td>上一题</td></tr>
        <tr><td><kbd>S</kbd></td><td>跳过本题</td></tr>
        <tr><td><kbd>F</kbd></td><td>标记待议</td></tr>
        <tr><td><kbd>U</kbd></td><td>撤销上一步</td></tr>
        <tr><td><kbd>Z</kbd></td><td>缩放 1:1 / 复位</td></tr>
        <tr><td>滚轮 / 拖拽 / 双击</td><td>缩放 / 平移 / 复位图片</td></tr>
        <tr><td><kbd>Esc</kbd></td><td>关闭弹层</td></tr>
      </table>
      <h3 style="margin:18px 0 6px;font-size:13px">导入格式</h3>
      <p class="sub" style="margin:0">zip 根目录放 <code>tasks.jsonl</code>（或 <code>tasks.csv</code>）+ <code>images/</code> + 可选 <code>config.json</code>；单图任务带 <code>items</code>（0/1），双图任务带 <code>images</code>、<code>criteria</code>、<code>scores</code>。详见 README。</p>
      <div class="modal-foot"><button class="btn primary" data-act="close-overlay">知道了</button></div>
    </div>`;
  }

  /* -------------------------------------------------------------- 导入 */
  function importHTML() {
    const server = store.state.source === 'server';
    return `<div class="modal">
      <h2>导入数据集</h2>
      <p class="sub">评分集 + 图片集，导入后即可开始核验。</p>
      ${
        server
          ? `<div class="field">
               <label>数据集名称</label>
               <input class="text-input" id="importName" placeholder="culture-v1（字母 / 数字 / - / _）">
             </div>
             <div class="field">
               <label>标题（可选）</label>
               <input class="text-input" id="importTitle" placeholder="文化 benchmark v1">
             </div>
             <div class="dropzone" id="dropzone">
               <input type="file" id="importFile" accept=".zip" hidden>
               <div class="drop-icon">＋</div>
               <p><b>选择或拖入 zip</b></p>
               <small>根目录：tasks.jsonl / tasks.csv + images/ + 可选 config.json</small>
             </div>
             <label class="checkline"><input type="checkbox" id="importOverwrite"> 覆盖同名数据集</label>
             <div class="import-status" id="importStatus"></div>
             <div class="modal-foot">
               <button class="btn ghost" data-act="close-overlay">取消</button>
               <button class="btn primary" data-act="do-import">开始导入</button>
             </div>`
          : `<div class="notice">
               当前是<b>本地演示模式</b>（直接打开 HTML，没有后端）。要以 zip 导入真实数据，先在终端运行：
             </div>
             <pre class="code-block">cd culture-verify
python server.py serve --port 8765 --open</pre>
             <p class="sub">然后访问 <code>http://127.0.0.1:8765</code>，右上角「导入数据」会变成可用状态。</p>
             <div class="modal-foot"><button class="btn primary" data-act="close-overlay">知道了</button></div>`
      }
    </div>`;
  }

  /* -------------------------------------------------------------- 导出 */
  function exportHTML(annotators = [], selected = '') {
    const stem = store.state.dataset.name || 'dataset';
    const server = store.state.source === 'server';
    const fileStem = `${stem}${selected ? `-${selected}` : ''}`;
    const item = (kind, title, desc, icon) => `<button class="export-item" data-act="export-${kind}">
      <span class="export-icon">${icon}</span>
      <span><b>${title}</b><small>${desc}</small></span>
    </button>`;
    const filter =
      server && annotators.length
        ? `<div class="export-filter">
             <label for="exportAnnotator">标注员</label>
             <select id="exportAnnotator">
               <option value="">全部标注员（合并）</option>
               ${annotators
                 .map(
                   (name) =>
                     `<option value="${esc(name)}" ${name === selected ? 'selected' : ''}>${esc(name)}</option>`
                 )
                 .join('')}
             </select>
           </div>`
        : '';
    return `<div class="modal">
      <h2>导出</h2>
      <p class="sub">${
        server
          ? selected
            ? `仅导出标注员 <b>${esc(selected)}</b> 的标注`
            : '从服务器数据目录导出（包含所有标注员）'
          : '从本地浏览器数据导出'
      }</p>
      ${filter}
      <div class="export-list">
        ${item('verdicts', '人工评分 CSV', '一行一条判定，含 AI 判断分、✓/✗、修正值，Excel 友好', '⊞')}
        ${item('consistency', '一致性报告 CSV', '分维度一致率、修正后通过率、Cohen\'s κ', '≡')}
        ${item('annotations', '标注 JSONL', '原始标注，可复现', '{ }')}
        ${item('summary', '汇总 JSON', '完整统计结构，方便画图', 'Σ')}
      </div>
      <div class="file-hint" id="exportFileHint">文件名以 <code>${esc(fileStem)}</code> 开头${
        selected ? ' · 单人导出时 κ 为空' : ''
      }</div>
      <div class="modal-foot"><button class="btn ghost" data-act="close-overlay">关闭</button></div>
    </div>`;
  }

  function annotatorHTML() {
    return `<div class="modal narrow">
      <h2>你是哪位标注员？</h2>
      <p class="sub">标注会记在这个名字下。同一题由两位以上标注员做过，结果页才会出现 Cohen's κ。</p>
      <div class="field">
        <label>名字</label>
        <input class="text-input" id="annotatorName" placeholder="例如 lin / wang / 标注-A" maxlength="40" autofocus>
      </div>
      <p class="field-hint">之后可以在右上角点自己的名字切换。</p>
      <div class="modal-foot">
        <button class="btn primary" data-act="save-annotator">开始标注</button>
      </div>
    </div>`;
  }

  CV.views = {
    headHTML,
    pointwiseView,
    pairwiseView,
    actionbarHTML,
    summaryHTML,
    settingsHTML,
    helpHTML,
    importHTML,
    exportHTML,
    emptyHTML,
    annotatorHTML,
  };
})(window.CV);
