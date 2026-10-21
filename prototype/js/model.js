/* 数据规范、标签解析、离线统计与导出（服务器模式由后端负责统计）。 */
window.CV = window.CV || {};
(function (CV) {
  'use strict';

  const { hashStr } = CV.utils;

  function normalizeDataset(payload) {
    const config = CV.config.defaultConfig();
    const rawConfig = payload.config || {};
    (rawConfig.dimensions || []).forEach((dim) => {
      if (!dim || !dim.id) return;
      config.labels[dim.id] = dim.label || dim.id;
      config.questions[dim.id] = dim.question || config.questions[dim.id] || '';
    });
    (rawConfig.criteria || []).forEach((crit) => {
      if (!crit || !crit.id) return;
      config.labels[crit.id] = crit.label || crit.id;
      config.questions[crit.id] = crit.question || config.questions[crit.id] || '';
    });

    const tasks = (payload.tasks || [])
      .map((task, index) => {
        const mode = task.mode || task.type || 'pointwise';
        if (mode === 'pointwise') {
          const items = (task.items || []).map((item, i) => ({
            ...item,
            dim: String(item.dim || item.id || `d${i + 1}`),
            score: Number(item.score),
          }));
          return { ...task, mode: 'pointwise', id: String(task.id), items };
        }
        const criteria = (task.criteria || Object.keys((task.scores && task.scores.A) || {})).map(
          (crit, i) => ({
            ...crit,
            id: String(crit.id || crit.dim || `q${i + 1}`),
          })
        );
        return {
          ...task,
          mode: 'pairwise',
          id: String(task.id),
          criteria,
          images: task.images || {},
          scores: task.scores || { A: {}, B: {} },
        };
      })
      .filter((task) => task.id);

    return { config, tasks, rawConfig };
  }

  const listOf = (tasks, mode) => tasks.filter((task) => task.mode === mode);
  const taskKey = (task) => `${task.mode}:${task.id}`;

  function itemIds(task) {
    return task.mode === 'pointwise'
      ? (task.items || []).map((item) => item.dim)
      : (task.criteria || []).map((crit) => crit.id);
  }

  function missingIds(task, ann) {
    const verdicts = (ann && ann.verdicts) || {};
    return itemIds(task).filter((id) => !verdicts[id]);
  }

  const isComplete = (task, ann) => missingIds(task, ann).length === 0;

  const labelFor = (config, id, fallback) =>
    (config.labels && config.labels[id]) || fallback || id;

  const questionFor = (config, id, fallback) =>
    config.questions && config.questions[id] != null
      ? config.questions[id]
      : fallback || '';

  function mediaUrl(dataset, rel) {
    const parts = String(rel || '')
      .split('/')
      .filter(Boolean)
      .map(encodeURIComponent);
    return `/media/${encodeURIComponent(dataset)}/${parts.join('/')}`;
  }

  function imageUrl(task, side, ctx) {
    const rel = side ? (task.images || {})[side] : task.image;
    if (!rel) return '';
    return ctx && ctx.source === 'server' ? mediaUrl(ctx.dataset, rel) : rel;
  }

  function modelPref(task, cid) {
    const a = Number(task.scores.A[cid]);
    const b = Number(task.scores.B[cid]);
    if (a === b) return 'tie';
    return a > b ? 'A' : 'B';
  }

  /* 空值判断：0 / false 是"有值"，不能被 || 吞掉 */
  const blank = (value) => (value === undefined || value === null || value === '' ? '' : value);

  /* 计入 corrected 的修正值：'?'（不确定）是"不知道真值"，不算一次修正 */
  const COUNTED_CORRECTIONS = ['0', '1', 'A', 'B', 'tie', 'gap'];
  const isCountedCorrection = (value) =>
    COUNTED_CORRECTIONS.includes(value === undefined || value === null ? '' : String(value));

  function pointTruth(item, verdict) {
    if (!verdict) return null;
    const correction = verdict.correction == null ? null : String(verdict.correction);
    if (correction === '0' || correction === '1') return Number(correction);
    if (verdict.agree === true) return Number(item.score);
    return null;
  }

  function pairTruth(pref, verdict) {
    if (!verdict) return null;
    if (verdict.agree === true) return pref;
    if (['A', 'B', 'tie'].includes(verdict.correction)) return verdict.correction;
    if (verdict.correction === 'gap') return pref;
    return null;
  }

  /* ------------------------------------------------------------------ 统计 */
  function emptyStats() {
    return {
      n: 0,
      agree: 0,
      disagree: 0,
      corrected: 0,
      truth_n: 0,
      raw_sum: 0,
      truth_sum: 0,
      correct_sum: 0,
      flipped: 0,
      duration_sum: 0,
      duration_n: 0,
    };
  }

  function finalize(stats, label, scope) {
    const out = {
      label,
      scope,
      n: stats.n,
      agree: stats.agree,
      disagree: stats.disagree,
      agreement_rate: stats.n ? stats.agree / stats.n : null,
      corrected: stats.corrected,
      truth_n: stats.truth_n,
      evaluator_accuracy: stats.truth_n ? stats.correct_sum / stats.truth_n : null,
    };
    if (scope === 'pointwise') {
      out.raw_pass_rate = stats.n ? stats.raw_sum / stats.n : null;
      out.verified_pass_rate = stats.truth_n ? stats.truth_sum / stats.truth_n : null;
    }
    if (scope === 'pairwise') out.flipped = stats.flipped;
    if (stats.duration_n) out.avg_duration_ms = Math.round(stats.duration_sum / stats.duration_n);
    return out;
  }

  function kappa(pairs) {
    if (!pairs.length) return { po: null, kappa: null };
    const n = pairs.length;
    let matches = 0;
    let p1 = 0;
    let q1 = 0;
    pairs.forEach(([a, b]) => {
      if (a === b) matches += 1;
      p1 += a;
      q1 += b;
    });
    const po = matches / n;
    const pe = (p1 / n) * (q1 / n) + (1 - p1 / n) * (1 - q1 / n);
    return { po, kappa: pe >= 1 ? null : (po - pe) / (1 - pe) };
  }

  function localStats(tasks, annotations, config) {
    const labels = { ...(config.labels || {}) };
    const taskById = new Map(tasks.map((task) => [task.id, task]));
    const dims = new Map();
    const crits = new Map();
    const byModel = new Map();
    const byAxis = new Map();
    const byAnnotator = new Map();
    const inter = new Map();
    const disagreements = [];
    const overall = emptyStats();
    const annotators = new Set();

    const bucketFor = (map, key) => {
      if (!map.has(key)) map.set(key, emptyStats());
      return map.get(key);
    };

    annotations.forEach((ann) => {
      const task = taskById.get(ann.task_id);
      if (!task) return;
      const annotator = ann.annotator || 'unknown';
      annotators.add(annotator);
      const verdicts = ann.verdicts || {};
      const annotStats = bucketFor(byAnnotator, annotator);
      const duration = Number(ann.duration_ms);
      if (Number.isFinite(duration) && duration >= 0) {
        annotStats.duration_sum += duration;
        annotStats.duration_n += 1;
        overall.duration_sum += duration;
        overall.duration_n += 1;
      }
      const axis = task.axis || '未标注';
      const axisStats = bucketFor(byAxis, axis);

      if (task.mode === 'pointwise') {
        const model = String((task.meta && task.meta.model) || 'unknown');
        const modelStats = bucketFor(byModel, model);
        (task.items || []).forEach((item) => {
          const verdict = verdicts[item.dim];
          if (!verdict || typeof verdict.agree !== 'boolean') return;
          const stats = bucketFor(dims, item.dim);
          [stats, overall, axisStats, modelStats].forEach((bucket) => {
            bucket.n += 1;
          });
          annotStats.n += 1;
          if (verdict.agree) {
            [stats, overall, axisStats, modelStats].forEach((bucket) => {
              bucket.agree += 1;
            });
            annotStats.agree += 1;
          } else {
            stats.disagree += 1;
            axisStats.disagree += 1;
            modelStats.disagree += 1;
            overall.disagree += 1;
            if (isCountedCorrection(verdict.correction)) {
              [stats, overall, axisStats, modelStats].forEach((bucket) => {
                bucket.corrected += 1;
              });
              annotStats.corrected += 1;
            }
            disagreements.push({
              task_id: task.id,
              task_mode: task.mode,
              item_id: item.dim,
              label: labels[item.dim] || item.dim,
              prompt: task.prompt,
              annotator,
              correction: verdict.correction || '',
            });
          }
          stats.raw_sum += item.score;
          modelStats.raw_sum += item.score;
          axisStats.raw_sum += item.score;
          const truth = pointTruth(item, verdict);
          if (truth != null) {
            [stats, overall, axisStats, modelStats].forEach((bucket) => {
              bucket.truth_n += 1;
              bucket.truth_sum += truth;
              if (Number(item.score) === truth) bucket.correct_sum += 1;
            });
            annotStats.truth_n += 1;
            annotStats.truth_sum += truth;
            if (Number(item.score) === truth) annotStats.correct_sum += 1;
          }
          const key = `${task.id}::${item.dim}`;
          if (!inter.has(key)) inter.set(key, {});
          inter.get(key)[annotator] = verdict.agree ? 1 : 0;
        });
      } else {
        (task.criteria || []).forEach((crit) => {
          const verdict = verdicts[crit.id];
          if (!verdict || typeof verdict.agree !== 'boolean') return;
          const pref = modelPref(task, crit.id);
          const stats = bucketFor(crits, crit.id);
          [stats, overall, axisStats].forEach((bucket) => {
            bucket.n += 1;
          });
          annotStats.n += 1;
          if (verdict.agree) {
            [stats, overall, axisStats].forEach((bucket) => {
              bucket.agree += 1;
            });
            annotStats.agree += 1;
          } else {
            stats.disagree += 1;
            axisStats.disagree += 1;
            overall.disagree += 1;
            if (isCountedCorrection(verdict.correction)) {
              [stats, overall, axisStats].forEach((bucket) => {
                bucket.corrected += 1;
              });
              annotStats.corrected += 1;
            }
            if (['A', 'B'].includes(verdict.correction) && verdict.correction !== pref) {
              stats.flipped += 1;
            }
            disagreements.push({
              task_id: task.id,
              task_mode: task.mode,
              item_id: crit.id,
              label: labels[crit.id] || crit.id,
              prompt: task.prompt,
              annotator,
              correction: verdict.correction || '',
            });
          }
          const truth = pairTruth(pref, verdict);
          if (truth != null) {
            [stats, overall, axisStats].forEach((bucket) => {
              bucket.truth_n += 1;
              if (truth === pref) bucket.correct_sum += 1;
            });
            annotStats.truth_n += 1;
            if (truth === pref) annotStats.correct_sum += 1;
          }
          const key = `${task.id}::${crit.id}`;
          if (!inter.has(key)) inter.set(key, {});
          inter.get(key)[annotator] = verdict.agree ? 1 : 0;
        });
      }
    });

    const dimensions = [...dims.entries()].map(([id, stats]) => ({
      id,
      ...finalize(stats, labels[id] || id, 'pointwise'),
    }));
    const criteria = [...crits.entries()].map(([id, stats]) => ({
      id,
      ...finalize(stats, labels[id] || id, 'pairwise'),
    }));

    const annotatorList = [...annotators].sort();
    const pairStats = [];
    for (let i = 0; i < annotatorList.length; i += 1) {
      for (let j = i + 1; j < annotatorList.length; j += 1) {
        const left = annotatorList[i];
        const right = annotatorList[j];
        const common = [];
        inter.forEach((values) => {
          if (values[left] != null && values[right] != null) {
            common.push([values[left], values[right]]);
          }
        });
        if (common.length < 2) continue;
        const result = kappa(common);
        pairStats.push({ n: common.length, po: result.po || 0, kappa: result.kappa });
      }
    }
    const totalCommon = pairStats.reduce((sum, item) => sum + item.n, 0);
    const kappas = pairStats.filter((item) => item.kappa != null);
    const kappaItems = kappas.reduce((sum, item) => sum + item.n, 0);
    const interSummary = {
      annotators: annotatorList,
      n_items: inter.size,
      n_comparisons: totalCommon,
      percent_agreement: totalCommon
        ? pairStats.reduce((sum, item) => sum + item.n * item.po, 0) / totalCommon
        : null,
      // 全判「同意」时 pe=1，κ 无定义：这类配对只进一致率，单独报出 κ 实际用到的比较数
      n_kappa_comparisons: kappaItems,
      kappa: kappas.length
        ? kappas.reduce((sum, item) => sum + item.n * item.kappa, 0) / kappaItems
        : null,
      n_pairs: pairStats.length,
    };

    const overallOut = finalize(overall, '全部维度', 'overall');
    return {
      generated_at: CV.utils.nowISO(),
      task_counts: {
        total: tasks.length,
        pointwise: tasks.filter((task) => task.mode === 'pointwise').length,
        pairwise: tasks.filter((task) => task.mode === 'pairwise').length,
      },
      annotation_count: annotations.length,
      annotated_tasks: new Set(
        annotations.map((ann) => ann.task_id).filter((id) => taskById.has(id))
      ).size,
      annotators: annotatorList,
      overall: overallOut,
      dimensions,
      criteria,
      inter_annotator: interSummary,
      by_annotator: [...byAnnotator.entries()]
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([annotator, stats]) => ({
          annotator,
          n: stats.n,
          agree: stats.agree,
          agreement_rate: stats.n ? stats.agree / stats.n : null,
          corrected: stats.corrected,
          avg_duration_ms: stats.duration_n
            ? Math.round(stats.duration_sum / stats.duration_n)
            : null,
        })),
      by_model: [...byModel.entries()].map(([model, stats]) => ({
        model,
        ...finalize(stats, model, 'pointwise'),
      })),
      by_axis: [...byAxis.entries()].map(([axis, stats]) => ({
        axis,
        ...finalize(stats, axis, 'overall'),
      })),
      disagreements,
    };
  }

  /* ------------------------------------------------------------------ 导出 */
  const VERDICT_COLUMNS = [
    'task_id',
    'mode',
    'annotator',
    'axis',
    'lang',
    'model',
    'item_id',
    'item_label',
    'model_score_a',
    'model_score_b',
    'model_pref',
    'human_agree',
    'human_correction',
    'human_truth',
    'overall',
    'note',
    'duration_ms',
    'finished_at',
    'status',
    'started_at',
    'model_a',
    'model_b',
    'human_verdict',
    'prompt',
    'shown_as',
    'region',
  ];

  function verdictRows(tasks, annotations, config) {
    const labels = config.labels || {};
    const taskById = new Map(tasks.map((task) => [task.id, task]));
    const rows = [];
    annotations.forEach((ann) => {
      const task = taskById.get(ann.task_id);
      if (!task) return;
      const verdicts = ann.verdicts || {};
      const meta = task.meta || {};
      const status = ann.status || '';
      const finished =
        ann.finished_at || (status === 'done' || status === 'flagged' ? ann.updated_at || '' : '');
      const base = {
        task_id: task.id,
        mode: task.mode,
        annotator: ann.annotator || '',
        axis: task.axis || '',
        lang: task.lang || '',
        overall: blank(ann.overall),
        note: blank(ann.note),
        duration_ms: blank(ann.duration_ms),
        finished_at: finished,
        status,
        started_at: blank(ann.started_at),
        prompt: task.prompt || '',
        shown_as: blank(ann.shown_as),
        region: task.region || '',
      };
      if (task.mode === 'pointwise') {
        (task.items || []).forEach((item) => {
          const verdict = verdicts[item.dim];
          if (!verdict) return;
          rows.push({
            ...base,
            model: meta.model || '',
            model_a: meta.model || '',
            model_b: '',
            item_id: item.dim,
            item_label: labels[item.dim] || item.dim,
            model_score_a: item.score,
            model_score_b: '',
            model_pref: '',
            human_agree: verdict.agree ? 1 : 0,
            human_correction: blank(verdict.correction),
            human_truth: pointTruth(item, verdict) == null ? '' : pointTruth(item, verdict),
            human_verdict: verdict.agree ? '同意' : '不同意',
          });
        });
      } else {
        const modelA = meta.model_A || '';
        const modelB = meta.model_B || '';
        (task.criteria || []).forEach((crit) => {
          const verdict = verdicts[crit.id];
          if (!verdict) return;
          const pref = modelPref(task, crit.id);
          rows.push({
            ...base,
            model: modelA && modelB ? `${modelA} vs ${modelB}` : modelA || modelB,
            model_a: modelA,
            model_b: modelB,
            item_id: crit.id,
            item_label: labels[crit.id] || crit.id,
            model_score_a: task.scores.A[crit.id],
            model_score_b: task.scores.B[crit.id],
            model_pref: pref,
            human_agree: verdict.agree ? 1 : 0,
            human_correction: blank(verdict.correction),
            human_truth: pairTruth(pref, verdict) || '',
            human_verdict: verdict.agree ? '同意' : '不同意',
          });
        });
      }
    });
    return rows;
  }

  const CONSISTENCY_COLUMNS = [
    'section',
    'key',
    'label',
    'n',
    'agree',
    'disagree',
    'agreement_rate',
    'corrected',
    'truth_n',
    'evaluator_accuracy',
    'raw_pass_rate',
    'verified_pass_rate',
    'flipped',
    'kappa',
    'kappa_n',
    'n_pairs',
    'n_items',
    'avg_duration_ms',
  ];

  function consistencyRows(summary) {
    const rows = [];
    const add = (section, key, label, item, extra = {}) => {
      const row = { section, key, label };
      CONSISTENCY_COLUMNS.forEach((col) => {
        if (!(col in row)) row[col] = item[col] == null ? '' : item[col];
      });
      rows.push({ ...row, ...extra });
    };
    add('overall', 'all', '全部判定', summary.overall, {
      kappa: (summary.inter_annotator || {}).kappa ?? '',
      kappa_n: (summary.inter_annotator || {}).n_kappa_comparisons ?? '',
    });
    (summary.dimensions || []).forEach((item) =>
      add('evaluator_vs_human', item.id, item.label, item)
    );
    (summary.criteria || []).forEach((item) =>
      add('evaluator_vs_human', item.id, item.label, item)
    );
    const inter = summary.inter_annotator || {};
    rows.push({
      section: 'inter_annotator',
      key: 'all',
      label: '多标注员一致性',
      n: inter.n_comparisons ?? '',
      agreement_rate: inter.percent_agreement ?? '',
      kappa: inter.kappa ?? '',
      kappa_n: inter.n_kappa_comparisons ?? '',
      n_pairs: inter.n_pairs ?? '',
      n_items: inter.n_items ?? '',
    });
    (summary.by_model || []).forEach((item) => add('by_model', item.model, item.model, item));
    (summary.by_axis || []).forEach((item) => add('by_axis', item.axis, item.axis, item));
    (summary.by_annotator || []).forEach((item) =>
      rows.push({
        section: 'by_annotator',
        key: item.annotator,
        label: item.annotator,
        n: item.n,
        agree: item.agree,
        agreement_rate: item.agreement_rate ?? '',
        corrected: item.corrected,
        avg_duration_ms: item.avg_duration_ms ?? '',
      })
    );
    return rows;
  }

  CV.model = {
    normalizeDataset,
    listOf,
    taskKey,
    itemIds,
    missingIds,
    isComplete,
    labelFor,
    questionFor,
    imageUrl,
    modelPref,
    pointTruth,
    pairTruth,
    localStats,
    verdictRows,
    consistencyRows,
    VERDICT_COLUMNS,
    CONSISTENCY_COLUMNS,
    randomOrder: (taskId, annotator) =>
      hashStr(`${taskId}:${annotator || 'local'}`) % 2 ? 'BA' : 'AB',
  };
})(window.CV);
