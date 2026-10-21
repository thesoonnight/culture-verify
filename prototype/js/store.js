/* 应用状态：加载数据集、读写标注、导航、撤销、汇总与导出。 */
window.CV = window.CV || {};
(function (CV) {
  'use strict';

  const { nowISO, query, downloadText, toCSV } = CV.utils;
  const { LS_KEY, LS_ANNOTATOR } = CV.config;
  const LS_LAST_DATASET = 'culture-verify-last-dataset';
  const LS_PREFS = 'culture-verify-prefs';

  const state = {
    ready: false,
    source: 'local', // local | server
    dataset: { name: 'demo', title: '内置演示数据集' },
    datasets: [],
    tasks: [],
    config: CV.config.defaultConfig(),
    annotations: {},
    annotator: 'local',
    mode: 'pointwise',
    idx: 0,
    showSummary: false,
    summary: null,
    summaryLoading: false,
    saveState: 'idle',
    saveMessage: '',
    busy: false,
    error: '',
    annotatorChosen: false,
    exportAnnotator: '',
    lastKey: null,
    viewStart: Date.now(),
    undo: [],
  };

  const saveChains = new Map();
  const saveTimers = new Map();

  const tasksFor = (mode) => CV.model.listOf(state.tasks, mode);
  const currentTask = () => {
    const list = tasksFor(state.mode);
    if (!list.length) return null;
    return list[CV.utils.clamp(state.idx, 0, list.length - 1)];
  };

  function setSave(status, message = '') {
    state.saveState = status;
    state.saveMessage = message;
    document.dispatchEvent(new CustomEvent('cv:save'));
  }

  function applyPrefs(config) {
    let prefs = {};
    try {
      prefs = JSON.parse(localStorage.getItem(LS_PREFS) || '{}');
    } catch (err) {
      prefs = {};
    }
    state.config = {
      ...config,
      labels: { ...config.labels },
      questions: { ...config.questions },
      showRationale: prefs.showRationale !== undefined ? prefs.showRationale : true,
      autoNext: !!prefs.autoNext,
      requireCorrection: !!prefs.requireCorrection,
    };
  }

  function savePrefs() {
    try {
      localStorage.setItem(
        LS_PREFS,
        JSON.stringify({
          showRationale: state.config.showRationale,
          autoNext: state.config.autoNext,
          requireCorrection: state.config.requireCorrection,
        })
      );
    } catch (err) {
      /* ignore */
    }
  }

  function loadLocal() {
    try {
      const data = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
      return {
        config: data.config || {},
        annotations: data.annotations || {},
      };
    } catch (err) {
      return { config: {}, annotations: {} };
    }
  }

  function saveLocal() {
    try {
      localStorage.setItem(
        LS_KEY,
        JSON.stringify({
          v: 2,
          config: state.config,
          annotations: state.annotations,
          saved_at: nowISO(),
        })
      );
      setSave('saved');
    } catch (err) {
      setSave('error', '本地存储不可用');
    }
  }

  function hydrateAnnotations(list) {
    const byId = new Map(state.tasks.map((task) => [task.id, task]));
    state.annotations = {};
    list.forEach((ann) => {
      const task = byId.get(ann.task_id);
      const mode = ann.mode || (task && task.mode) || 'pointwise';
      state.annotations[`${mode}:${ann.task_id}`] = { ...ann, mode };
    });
  }

  function ensureAnn(task) {
    const key = CV.model.taskKey(task);
    let ann = state.annotations[key];
    if (!ann) {
      ann = {
        task_id: task.id,
        mode: task.mode,
        annotator: state.annotator,
        status: 'doing',
        verdicts: {},
        note: '',
        started_at: nowISO(),
        shown_as:
          task.mode === 'pairwise'
            ? CV.model.randomOrder(task.id, state.annotator)
            : undefined,
      };
      state.annotations[key] = ann;
    }
    if (!ann.verdicts) ann.verdicts = {};
    return ann;
  }

  function isDone(task) {
    const ann = state.annotations[CV.model.taskKey(task)];
    return !!ann && (ann.status === 'done' || ann.status === 'flagged');
  }

  function firstUndoneIndex(mode) {
    const list = tasksFor(mode);
    const index = list.findIndex((task) => !isDone(task));
    return index === -1 ? 0 : index;
  }

  function touchTask(task) {
    const key = CV.model.taskKey(task);
    if (state.lastKey !== key) {
      state.lastKey = key;
      state.viewStart = Date.now();
    }
  }

  function persist(ann, { debounce = 0 } = {}) {
    if (state.source === 'local') {
      saveLocal();
      return;
    }
    const run = () => {
      const snapshot = JSON.parse(JSON.stringify(ann));
      const key = CV.model.taskKey(ann);
      const previous = saveChains.get(key) || Promise.resolve();
      setSave('saving');
      const job = previous
        .catch(() => {})
        .then(() => CV.api.saveAnnotation(state.dataset.name, snapshot))
        .then(() => setSave('saved'))
        .catch((err) => setSave('error', err.message || '保存失败'));
      saveChains.set(key, job);
    };
    if (debounce > 0) {
      const key = CV.model.taskKey(ann);
      clearTimeout(saveTimers.get(key));
      saveTimers.set(
        key,
        setTimeout(() => {
          saveTimers.delete(key);
          run();
        }, debounce)
      );
    } else {
      run();
    }
  }

  function finish(task, status) {
    const ann = ensureAnn(task);
    // 耗时只记第一次：回看已完成的题再按「下一题」不该把 8 万多毫秒覆盖成 1 秒
    const firstFinish = ann.duration_ms == null;
    ann.status = status;
    ann.finished_at = ann.finished_at || nowISO();
    if (firstFinish) ann.duration_ms = Date.now() - state.viewStart;
    ann.updated_at = nowISO();
    persist(ann);
  }

  function setVote(task, id, agree) {
    const ann = ensureAnn(task);
    const previous = ann.verdicts[id] ? { ...ann.verdicts[id] } : null;
    if (previous && previous.agree === agree) {
      delete ann.verdicts[id];
    } else {
      ann.verdicts[id] = { agree, correction: previous ? previous.correction : undefined };
    }
    state.undo.push({ key: CV.model.taskKey(task), id, previous });
    if (state.undo.length > 100) state.undo.shift();
    ann.updated_at = nowISO();
    persist(ann);
    return ann;
  }

  function setCorrection(task, id, value) {
    const ann = ensureAnn(task);
    if (!ann.verdicts[id]) return;
    ann.verdicts[id].correction = value || undefined;
    ann.updated_at = nowISO();
    persist(ann);
  }

  function setOverall(task, value) {
    const ann = ensureAnn(task);
    ann.overall = ann.overall === value ? null : value;
    ann.updated_at = nowISO();
    persist(ann);
  }

  function setNote(task, value, debounce = 450) {
    const ann = ensureAnn(task);
    ann.note = value;
    ann.updated_at = nowISO();
    persist(ann, { debounce });
  }

  function next() {
    const task = currentTask();
    if (!task) return { ok: false, reason: 'empty' };
    const ann = ensureAnn(task);
    const missing = CV.model.missingIds(task, ann);
    if (missing.length) return { ok: false, reason: 'missing', missing };
    if (state.config.requireCorrection) {
      const uncovered = CV.model
        .itemIds(task)
        .filter(
          (id) => ann.verdicts[id] && ann.verdicts[id].agree === false && !ann.verdicts[id].correction
        );
      if (uncovered.length) return { ok: false, reason: 'correction', items: uncovered };
    }
    finish(task, ann.status === 'flagged' ? 'flagged' : 'done');
    state.idx += 1;
    return { ok: true };
  }

  function prev() {
    if (state.idx <= 0) return false;
    state.idx -= 1;
    state.showSummary = false;
    return true;
  }

  function skip() {
    const task = currentTask();
    if (!task) return;
    // 标了「待议」的题按 S 跳过时别把标记弄丢
    const ann = ensureAnn(task);
    finish(task, ann.status === 'flagged' ? 'flagged' : 'skipped');
    state.idx += 1;
  }

  function flag() {
    const task = currentTask();
    if (!task) return null;
    const ann = ensureAnn(task);
    ann.status = ann.status === 'flagged' ? 'doing' : 'flagged';
    ann.updated_at = nowISO();
    persist(ann);
    return ann.status;
  }

  /* 交换左右：显示顺序变了，落库的 shown_as 必须跟着变（否则位置偏差对不上）。
     已经投过票的题先清空判定，避免同一行数据对应两种显示顺序。 */
  function swapOrder() {
    const task = currentTask();
    if (!task || task.mode !== 'pairwise') return { ok: false, cleared: 0 };
    const ann = ensureAnn(task);
    const cleared = Object.keys(ann.verdicts || {}).length;
    ann.verdicts = {};
    ann.shown_as = ann.shown_as === 'AB' ? 'BA' : 'AB';
    ann.updated_at = nowISO();
    persist(ann);
    return { ok: true, cleared };
  }

  async function deleteMyAnnotations() {
    if (state.source !== 'server' || !state.dataset.name) return 0;
    const result = await CV.api.deleteAnnotations(state.dataset.name, { annotator: state.annotator });
    state.annotations = {};
    state.undo = [];
    state.idx = 0;
    state.showSummary = false;
    state.summary = null;
    return result.deleted || 0;
  }

  function undo() {
    const entry = state.undo.pop();
    if (!entry) return null;
    const sep = entry.key.indexOf(':');
    const mode = entry.key.slice(0, sep);
    const id = entry.key.slice(sep + 1);
    const list = tasksFor(mode);
    const index = list.findIndex((task) => task.id === id);
    if (index < 0) return null;
    state.mode = mode;
    state.idx = index;
    state.showSummary = false;
    const task = list[index];
    const ann = ensureAnn(task);
    if (entry.previous) ann.verdicts[entry.id] = entry.previous;
    else delete ann.verdicts[entry.id];
    ann.updated_at = nowISO();
    persist(ann);
    return task;
  }

  function setMode(mode) {
    state.mode = mode;
    state.showSummary = false;
    state.idx = firstUndoneIndex(mode);
  }

  /* ------------------------------------------------------------ 加载/切换 */
  async function refreshDatasets() {
    state.datasets = await CV.api.listDatasets();
    return state.datasets;
  }

  async function loadDataset(name) {
    state.busy = true;
    state.error = '';
    try {
      const payload = await CV.api.loadDataset(name);
      const normalized = CV.model.normalizeDataset(payload);
      state.dataset = payload.dataset || { name };
      state.tasks = normalized.tasks;
      applyPrefs(normalized.config);
      state.annotations = {};
      const annotations = await CV.api.getAnnotations(name, state.annotator);
      hydrateAnnotations(annotations);
      const params = query();
      const urlMode = params.get('mode');
      const preferred = urlMode === 'pairwise' || urlMode === 'pointwise' ? urlMode : state.mode;
      const available =
        normalized.tasks.some((task) => task.mode === preferred)
          ? preferred
          : normalized.tasks.some((task) => task.mode === 'pointwise')
            ? 'pointwise'
            : 'pairwise';
      state.mode = available;
      state.idx = firstUndoneIndex(state.mode);
      state.showSummary = false;
      state.summary = null;
      state.summaryLoading = false;
      state.saveState = 'idle';
      state.saveMessage = '';
      state.undo = [];
      state.lastKey = null;
      localStorage.setItem(LS_LAST_DATASET, name);
      return payload;
    } finally {
      state.busy = false;
    }
  }

  function loadDemo() {
    state.source = 'local';
    const normalized = CV.model.normalizeDataset(CV.demo);
    const saved = loadLocal();
    const config = {
      ...normalized.config,
      ...saved.config,
      labels: { ...normalized.config.labels, ...((saved.config || {}).labels || {}) },
      questions: { ...normalized.config.questions, ...((saved.config || {}).questions || {}) },
    };
    applyPrefs(config);
    state.dataset = { ...CV.demo.dataset };
    state.tasks = normalized.tasks;
    state.annotations = saved.annotations || {};
    const params = query();
    state.mode = params.get('mode') === 'pairwise' ? 'pairwise' : 'pointwise';
    state.idx = firstUndoneIndex(state.mode);
    state.showSummary = false;
    state.summary = null;
    state.ready = true;
  }

  async function boot() {
    const params = query();
    const forceDemo = params.get('demo') === '1';
    const mode = forceDemo ? 'local' : await CV.api.boot();
    state.source = mode;
    if (mode === 'server') {
      const fromUrl = params.get('annotator');
      const stored = localStorage.getItem(LS_ANNOTATOR);
      state.annotator = fromUrl || stored || 'local';
      state.annotatorChosen = !!(fromUrl || stored);
      if (fromUrl) localStorage.setItem(LS_ANNOTATOR, fromUrl);
      await refreshDatasets();
      const wanted = params.get('dataset') || localStorage.getItem(LS_LAST_DATASET);
      const pick = state.datasets.find((item) => item.name === wanted) || state.datasets[0];
      if (pick) {
        await loadDataset(pick.name);
      } else {
        state.dataset = { name: '', title: '还没有数据集' };
        state.tasks = [];
        state.config = CV.config.defaultConfig();
        applyPrefs(state.config);
        state.showSummary = false;
      }
    } else {
      state.annotator = 'local';
      loadDemo();
    }
    state.ready = true;
    return mode;
  }

  async function setAnnotator(name) {
    const clean = String(name || '').trim().slice(0, 40) || 'local';
    state.annotator = clean;
    state.annotatorChosen = true;
    localStorage.setItem(LS_ANNOTATOR, clean);
    if (state.source === 'server' && state.dataset.name) {
      state.busy = true;
      try {
        const annotations = await CV.api.getAnnotations(state.dataset.name, clean);
        hydrateAnnotations(annotations);
        state.idx = firstUndoneIndex(state.mode);
      } finally {
        state.busy = false;
      }
    }
  }

  async function importZip(name, file, options = {}) {
    const result = await CV.api.importZip(name, file, options);
    await refreshDatasets();
    await loadDataset(name);
    return result;
  }

  async function setLabels(labels, questions) {
    state.config.labels = { ...state.config.labels, ...labels };
    state.config.questions = { ...state.config.questions, ...questions };
    if (state.source === 'server' && state.dataset.name) {
      await CV.api.updateConfig(state.dataset.name, labels, questions);
    } else {
      saveLocal();
    }
  }

  function savePreferences() {
    savePrefs();
    if (state.source === 'local') saveLocal();
  }

  async function loadSummary() {
    state.summaryLoading = true;
    state.summary = null;
    try {
      if (state.source === 'server' && state.dataset.name) {
        const [stats, allAnnotations] = await Promise.all([
          CV.api.stats(state.dataset.name),
          CV.api.getAnnotations(state.dataset.name),
        ]);
        const local = CV.model.localStats(state.tasks, allAnnotations, state.config);
        stats.disagreements = local.disagreements;
        state.summary = stats;
      } else {
        state.summary = CV.model.localStats(
          state.tasks,
          Object.values(state.annotations),
          state.config
        );
      }
    } finally {
      state.summaryLoading = false;
    }
    return state.summary;
  }

  function localExport(kind, annotator = '') {
    const all = Object.values(state.annotations);
    const annotations = annotator
      ? all.filter((ann) => (ann.annotator || 'local') === annotator)
      : all;
    const summary = CV.model.localStats(state.tasks, annotations, state.config);
    const suffix = annotator ? `-${annotator}` : '';
    const stem = `${state.dataset.name || 'demo'}${suffix}`;
    if (kind === 'verdicts') {
      const rows = CV.model.verdictRows(state.tasks, annotations, state.config);
      downloadText(toCSV(rows, CV.model.VERDICT_COLUMNS), `${stem}-verdicts.csv`, 'text/csv;charset=utf-8');
      return `${stem}-verdicts.csv`;
    }
    if (kind === 'consistency') {
      const rows = CV.model.consistencyRows(summary);
      downloadText(toCSV(rows, CV.model.CONSISTENCY_COLUMNS), `${stem}-consistency.csv`, 'text/csv;charset=utf-8');
      return `${stem}-consistency.csv`;
    }
    if (kind === 'annotations') {
      const text = annotations.map((ann) => JSON.stringify(ann)).join('\n') + '\n';
      downloadText(text, `${stem}-annotations.jsonl`, 'application/x-ndjson;charset=utf-8');
      return `${stem}-annotations.jsonl`;
    }
    const payload = {
      schema: 'culture-verify/summary@0.2.1',
      exported_at: nowISO(),
      dataset: state.dataset,
      annotator: annotator || null,
      config: state.config,
      summary,
    };
    downloadText(JSON.stringify(payload, null, 2), `${stem}-summary.json`, 'application/json;charset=utf-8');
    return `${stem}-summary.json`;
  }

  function exportKind(kind, annotator = '') {
    if (state.source === 'server' && state.dataset.name) {
      const url = CV.api.exportUrl(state.dataset.name, kind, annotator || undefined);
      window.location.href = url;
      return `${state.dataset.name}${annotator ? `-${annotator}` : ''}-${kind}`;
    }
    return localExport(kind, annotator);
  }

  function resetLocal() {
    state.annotations = {};
    state.undo = [];
    state.idx = 0;
    state.showSummary = false;
    state.summary = null;
    state.config = CV.config.defaultConfig();
    try {
      localStorage.removeItem(LS_KEY);
    } catch (err) {
      /* ignore */
    }
    setSave('idle');
  }

  CV.store = {
    state,
    tasksFor,
    currentTask,
    ensureAnn,
    isDone,
    firstUndoneIndex,
    touchTask,
    setVote,
    setCorrection,
    setOverall,
    setNote,
    next,
    prev,
    skip,
    flag,
    swapOrder,
    deleteMyAnnotations,
    undo,
    setMode,
    boot,
    loadDataset,
    refreshDatasets,
    setAnnotator,
    importZip,
    setLabels,
    savePreferences,
    loadSummary,
    exportKind,
    resetLocal,
    persist,
    useDemo: loadDemo,
  };
})(window.CV);
