/* 应用入口：渲染、事件、缩放、弹层、导入导出。 */
window.CV = window.CV || {};
(function (CV) {
  'use strict';

  const { $, $$, clamp, query, esc, sleep } = CV.utils;
  const store = CV.store;
  const state = store.state;
  const views = CV.views;

  const view = $('#view');
  const actionbar = $('#actionbar');
  const drawer = $('#drawer');
  const scrim = $('#scrim');
  const overlay = $('#overlay');
  const toastEl = $('#toast');

  let zoom = { scale: 1, x: 0, y: 0 };
  let zoomKey = null;
  let autoTimer = null;
  let selectedImportFile = null;

  /* ------------------------------------------------------------------ 渲染 */
  function loadingHTML(text) {
    return `<div class="loading-wrap"><div class="loading-ring"></div><p>${esc(text)}</p></div>`;
  }

  function emptyModeHTML(mode) {
    const other = mode === 'pointwise' ? 'pairwise' : 'pointwise';
    return `<section class="summary"><div class="empty-card">
      <h1>这个数据集没有${mode === 'pointwise' ? '单图' : '双图'}题</h1>
      <p>切到另一条流程，或导入包含该类型题目的数据集。</p>
      <button class="btn primary" data-mode="${other}">去看${other === 'pointwise' ? '单图核验' : '双图对比'}</button>
    </div></section>`;
  }

  function renderChrome() {
    const select = $('#datasetSelect');
    const picker = $('#datasetPicker');
    if (state.source === 'server') {
      picker.classList.remove('is-local');
      const options = state.datasets.map(
        (item) =>
          `<option value="${esc(item.name)}">${esc(item.title || item.name)} · ${item.task_count || 0} 题</option>`
      );
      select.innerHTML = options.join('') || '<option value="">（无数据集）</option>';
      select.disabled = !state.datasets.length;
      if (state.dataset.name) select.value = state.dataset.name;
    } else {
      picker.classList.add('is-local');
      select.innerHTML = '<option>内置演示数据集</option>';
      select.disabled = true;
    }

    const donePoint = store.tasksFor('pointwise').filter((task) => store.isDone(task)).length;
    const totalPoint = store.tasksFor('pointwise').length;
    const donePair = store.tasksFor('pairwise').filter((task) => store.isDone(task)).length;
    const totalPair = store.tasksFor('pairwise').length;
    $('#tabCountA').textContent = `${donePoint} / ${totalPoint}`;
    $('#tabCountB').textContent = `${donePair} / ${totalPair}`;
    $$('.tab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.mode === state.mode && !state.showSummary);
    });

    if (state.showSummary) $('#counter').textContent = '结果';
    else {
      const list = store.tasksFor(state.mode);
      $('#counter').textContent = list.length ? `${Math.min(state.idx + 1, list.length)} / ${list.length}` : '—';
    }

    const allDone = state.tasks.filter((task) => store.isDone(task)).length;
    $('#progressFill').style.width = `${state.tasks.length ? (allDone / state.tasks.length) * 100 : 0}%`;
    $('#annotatorChip').textContent = state.annotator;
    $('#brandSub').textContent = state.source === 'server' ? `服务器 · ${state.tasks.length} 题` : '本地演示模式';
    updateSaveIndicator();
    document.title = state.dataset.title
      ? `文化核验台 · ${state.dataset.title}`
      : '文化核验台';
  }

  function updateSaveIndicator() {
    const el = $('#saveState');
    if (!el) return;
    const labels = {
      idle: state.source === 'server' ? '就绪' : '本机',
      saving: '保存中…',
      saved: '已保存',
      error: '保存失败',
    };
    el.className = `save-state ${state.saveState}`;
    el.querySelector('em').textContent = labels[state.saveState] || '就绪';
    el.title = state.saveMessage || '';
  }

  function render() {
    renderChrome();
    if (!state.ready) {
      view.innerHTML = loadingHTML('启动中…');
      actionbar.innerHTML = '';
      return;
    }
    if (state.busy) {
      view.innerHTML = loadingHTML('加载数据集…');
      actionbar.innerHTML = '';
      return;
    }
    if (!state.tasks.length) {
      view.innerHTML = views.emptyHTML();
      actionbar.innerHTML = '';
      return;
    }
    if (state.showSummary) {
      view.innerHTML = views.summaryHTML(state.summary);
      actionbar.innerHTML = '';
      return;
    }
    const list = store.tasksFor(state.mode);
    if (!list.length) {
      view.innerHTML = emptyModeHTML(state.mode);
      actionbar.innerHTML = '';
      return;
    }
    if (state.idx >= list.length) {
      openSummary();
      return;
    }
    const task = list[state.idx];
    const key = CV.model.taskKey(task);
    if (key !== zoomKey) {
      zoomKey = key;
      zoom = { scale: 1, x: 0, y: 0 };
    }
    view.innerHTML =
      task.mode === 'pointwise' ? views.pointwiseView(task) : views.pairwiseView(task);
    actionbar.innerHTML = views.actionbarHTML(task);
    bindStage();
    if (zoom.scale !== 1 || zoom.x || zoom.y) applyZoom();
    updateActionState();
    window.scrollTo(0, 0);
    preloadNext();
  }

  function preloadNext() {
    const list = store.tasksFor(state.mode);
    const next = list[state.idx + 1];
    if (!next) return;
    const ctx = { source: state.source, dataset: state.dataset.name };
    if (next.mode === 'pointwise') {
      const image = new Image();
      image.src = CV.model.imageUrl(next, null, ctx);
    } else {
      ['A', 'B'].forEach((side) => {
        const image = new Image();
        image.src = CV.model.imageUrl(next, side, ctx);
      });
    }
  }

  function updateActionState() {
    const task = store.currentTask();
    if (!task) return;
    const ann = store.ensureAnn(task);
    const flag = $('[data-act="flag"]');
    if (flag) flag.classList.toggle('warn', ann.status === 'flagged');
    const next = $('[data-act="next"]');
    if (next) next.classList.toggle('is-ready', CV.model.isComplete(task, ann));
  }

  function refreshVerdict(id) {
    const task = store.currentTask();
    if (!task) return;
    const host = document.querySelector(`[data-dim="${id}"], [data-crit="${id}"]`);
    if (!host) return;
    const ann = store.ensureAnn(task);
    const verdict = ann.verdicts[id];
    host.classList.toggle('is-agree', !!verdict && verdict.agree === true);
    host.classList.toggle('is-disagree', !!verdict && verdict.agree === false);
    $$('[data-vote]', host).forEach((button) => {
      const active = !!verdict && verdict.agree === (button.dataset.vote === '1');
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    const correction = $('.correction', host);
    if (correction) correction.classList.toggle('show', !!verdict && verdict.agree === false);
    $$('[data-corr]', host).forEach((button) => {
      button.classList.toggle('active', !!verdict && verdict.correction === button.dataset.corr);
    });
    const wrap = $('.corr-select-wrap', host);
    if (wrap) wrap.classList.toggle('show', !!verdict && verdict.agree === false);
    const select = $('.corr-select', host);
    if (select) select.value = (verdict && verdict.correction) || '';
  }

  function maybeAutoNext() {
    const task = store.currentTask();
    if (!task || !state.config.autoNext) return;
    const ann = store.ensureAnn(task);
    if (!CV.model.isComplete(task, ann)) return;
    clearTimeout(autoTimer);
    autoTimer = setTimeout(() => {
      if (store.currentTask() === task && CV.model.isComplete(task, store.ensureAnn(task))) {
        goNext();
      }
    }, 600);
  }

  function goNext() {
    clearTimeout(autoTimer);
    const result = store.next();
    if (!result.ok) {
      if (result.reason === 'missing') {
        toast(`还有 ${result.missing.length} 项未核验 · 也可以按 S 跳过`);
        shake(result.missing);
      } else if (result.reason === 'correction') {
        toast('有 ✗ 的项还没填「实际应为」');
        shake(result.items);
      }
      return;
    }
    if (state.idx >= store.tasksFor(state.mode).length) openSummary();
    else render();
  }

  function goPrev() {
    if (!store.prev()) toast('已经是第一题');
    else render();
  }

  function goSkip() {
    store.skip();
    if (state.idx >= store.tasksFor(state.mode).length) openSummary();
    else render();
  }

  function goFlag() {
    const status = store.flag();
    if (status == null) return;
    updateActionState();
    toast(status === 'flagged' ? '已标记待议（再按 F 取消）' : '已取消待议');
  }

  function goUndo() {
    const task = store.undo();
    if (!task) {
      toast('没有可撤销的操作');
      return;
    }
    render();
    toast('已撤销上一步');
  }

  function shake(ids) {
    (ids || []).forEach((id) => {
      const host = document.querySelector(`[data-dim="${id}"], [data-crit="${id}"]`);
      if (!host) return;
      host.classList.add('shake');
      setTimeout(() => host.classList.remove('shake'), 350);
    });
  }

  /* ------------------------------------------------------------------ 汇总 */
  function openSummary() {
    if (!state.tasks.length) return;
    state.showSummary = true;
    state.summary = null;
    state.summaryLoading = true;
    render();
    store
      .loadSummary()
      .then(() => {
        if (state.showSummary) render();
      })
      .catch((err) => {
        state.summaryLoading = false;
        toast(`统计加载失败：${err.message}`);
        render();
      });
  }

  /* ------------------------------------------------------------------ 缩放 */
  function applyZoom() {
    $$('.zoom-layer').forEach((el) => {
      el.style.transform = `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.scale})`;
    });
  }

  function zoomBy(factor) {
    zoom.scale = clamp(zoom.scale * factor, 1, 6);
    applyZoom();
  }

  function zoomFull() {
    const image = $('.zoom-layer img');
    if (!image || !image.clientWidth) return;
    zoom.scale = clamp(image.naturalWidth / image.clientWidth, 1, 6);
    zoom.x = 0;
    zoom.y = 0;
    applyZoom();
  }

  function resetZoom() {
    zoom = { scale: 1, x: 0, y: 0 };
    applyZoom();
  }

  function bindStage() {
    $$('.stage').forEach((stage) => {
      stage.addEventListener(
        'wheel',
        (e) => {
          e.preventDefault();
          zoom.scale = clamp(zoom.scale * Math.exp(-e.deltaY * 0.0012), 1, 6);
          applyZoom();
        },
        { passive: false }
      );
      stage.addEventListener('pointerdown', (e) => {
        if (e.target.closest('.tool')) return;
        stage.dataset.dragX = e.clientX;
        stage.dataset.dragY = e.clientY;
        stage.dataset.originX = zoom.x;
        stage.dataset.originY = zoom.y;
        stage.dataset.dragging = '1';
        stage.setPointerCapture(e.pointerId);
      });
      stage.addEventListener('pointermove', (e) => {
        if (stage.dataset.dragging !== '1') return;
        zoom.x = Number(stage.dataset.originX) + (e.clientX - Number(stage.dataset.dragX));
        zoom.y = Number(stage.dataset.originY) + (e.clientY - Number(stage.dataset.dragY));
        applyZoom();
      });
      const end = () => {
        stage.dataset.dragging = '0';
      };
      stage.addEventListener('pointerup', end);
      stage.addEventListener('pointercancel', end);
      stage.addEventListener('dblclick', (e) => {
        if (e.target.closest('.tool')) return;
        resetZoom();
      });
    });
  }

  /* ------------------------------------------------------------------ 弹层 */
  function openModal(html, kind) {
    overlay.hidden = false;
    overlay.innerHTML = html;
    overlay.dataset.kind = kind;
  }

  function closeOverlay(force = false) {
    if (!force && overlay.dataset.kind === 'annotator') return; // 先起名字再开始
    overlay.hidden = true;
    overlay.innerHTML = '';
    delete overlay.dataset.kind;
    selectedImportFile = null;
  }

  function openHelp() {
    openModal(views.helpHTML(), 'help');
  }

  function openAnnotator() {
    openModal(views.annotatorHTML(), 'annotator');
    setTimeout(() => {
      const input = $('#annotatorName');
      if (input) input.focus();
    }, 50);
  }

  async function saveAnnotator() {
    const input = $('#annotatorName');
    const name = input ? input.value.trim() : '';
    if (!name) {
      toast('请输入一个名字');
      return;
    }
    try {
      await store.setAnnotator(name);
      closeOverlay(true);
      render();
      toast(`标注员：${state.annotator}`);
    } catch (err) {
      toast(`切换失败：${err.message}`);
    }
  }

  async function openExport() {
    let annotators = [];
    if (state.source === 'server' && state.dataset.name) {
      try {
        await store.refreshDatasets();
      } catch (err) {
        /* 拉不到就用旧列表 */
      }
      const meta = state.datasets.find((item) => item.name === state.dataset.name);
      annotators = (meta && meta.annotators ? meta.annotators : []).slice().sort();
    } else {
      annotators = [
        ...new Set(Object.values(state.annotations).map((ann) => ann.annotator || 'local')),
      ].sort();
    }
    if (state.exportAnnotator && !annotators.includes(state.exportAnnotator)) {
      state.exportAnnotator = '';
    }
    openModal(views.exportHTML(annotators, state.exportAnnotator), 'export');
  }

  function openImport() {
    openModal(views.importHTML(), 'import');
    if (state.source !== 'server') return;
    const drop = $('#dropzone');
    const input = $('#importFile');
    const setFile = (file) => {
      selectedImportFile = file || null;
      const nameEl = drop.querySelector('p b');
      if (nameEl) nameEl.textContent = file ? file.name : '选择或拖入 zip';
      const status = $('#importStatus');
      if (status) status.textContent = file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : '';
    };
    input.addEventListener('change', () => setFile(input.files[0]));
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('dragover', (e) => {
      e.preventDefault();
      drop.classList.add('over');
    });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', (e) => {
      e.preventDefault();
      drop.classList.remove('over');
      setFile(e.dataTransfer.files[0]);
    });
  }

  async function doImport() {
    if (state.source !== 'server') return;
    const name = ($('#importName') || {}).value?.trim() || '';
    const title = ($('#importTitle') || {}).value?.trim() || '';
    const status = $('#importStatus');
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(name)) {
      if (status) status.textContent = '数据集名称只允许字母、数字、-、_';
      return;
    }
    if (!selectedImportFile) {
      if (status) status.textContent = '先选择或拖入一个 zip';
      return;
    }
    const overwrite = !!($('#importOverwrite') || {}).checked;
    if (status) status.textContent = '导入中…';
    try {
      await store.importZip(name, selectedImportFile, { title, overwrite });
      closeOverlay();
      toast(`已导入 ${name}`);
      render();
      if (!state.annotatorChosen) setTimeout(openAnnotator, 80);
    } catch (err) {
      if (status) status.textContent = `导入失败：${err.message}`;
    }
  }

  function openLightbox(src) {
    overlay.hidden = false;
    overlay.dataset.kind = 'lightbox';
    overlay.innerHTML = `<div class="lightbox"><span class="close-hint">Esc 关闭</span><img src="${esc(src)}" alt=""></div>`;
  }

  function closeAll() {
    closeOverlay();
    if (drawer.classList.contains('open')) closeSettings(false);
  }

  /* ------------------------------------------------------------------ 设置 */
  function openSettings() {
    drawer.innerHTML = views.settingsHTML();
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    scrim.hidden = false;
  }

  async function closeSettings(save = true) {
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    scrim.hidden = true;
    if (!save) return;
    try {
      await store.setLabels({ ...state.config.labels }, { ...state.config.questions });
      render();
      toast('维度名称已保存');
    } catch (err) {
      toast(`保存失败：${err.message}`);
    }
  }

  async function switchAnnotator() {
    const input = $('#annotatorInput');
    if (!input) return;
    try {
      await store.setAnnotator(input.value);
      await closeSettings(false);
      render();
      toast(`已切换到标注员 ${state.annotator}`);
    } catch (err) {
      toast(`切换失败：${err.message}`);
    }
  }

  async function restoreLabels() {
    const point = CV.config.DEFAULT_DIMENSIONS;
    const pair = CV.config.DEFAULT_CRITERIA;
    [...point, ...pair].forEach((item) => {
      state.config.labels[item.id] = item.label;
      state.config.questions[item.id] = item.question;
    });
    drawer.innerHTML = views.settingsHTML();
    await store.setLabels({ ...state.config.labels }, { ...state.config.questions });
    render();
    toast('已恢复默认名称');
  }

  function resetLocal() {
    if (!window.confirm('清空本地所有核验记录与维度改名？此操作不可撤销。')) return;
    store.resetLocal();
    state.showSummary = false;
    render();
    toast('已清空本地数据');
  }

  async function resetAnnotations() {
    const name = state.dataset.name;
    if (!name) return;
    if (
      !window.confirm(
        `清空标注员「${state.annotator}」在「${name}」上的全部标注？\n只删你自己的，别人的不受影响，但删了不可恢复。`
      )
    ) {
      return;
    }
    try {
      const deleted = await store.deleteMyAnnotations();
      await closeSettings(false);
      render();
      toast(`已清空 ${deleted} 条标注`);
    } catch (err) {
      toast(`清空失败：${err.message}`);
    }
  }

  function jumpTask(taskId) {
    const task = state.tasks.find((item) => item.id === taskId);
    if (!task) return;
    state.mode = task.mode;
    state.showSummary = false;
    state.idx = store.tasksFor(task.mode).findIndex((item) => item.id === taskId);
    render();
  }

  function doExport(kind) {
    try {
      const name = store.exportKind(kind, state.exportAnnotator || '');
      toast(`已导出 ${name}`);
      closeOverlay();
    } catch (err) {
      toast(`导出失败：${err.message}`);
    }
  }

  /* ---------------------------------------------------------------- 动作表 */
  function handleAction(action, el) {
    switch (action) {
      case 'settings':
        openSettings();
        break;
      case 'close-drawer':
        closeSettings(true);
        break;
      case 'help':
        openHelp();
        break;
      case 'close-overlay':
        closeOverlay();
        break;
      case 'import':
        openImport();
        break;
      case 'export':
        openExport();
        break;
      case 'summary':
        openSummary();
        break;
      case 'back':
        state.showSummary = false;
        render();
        break;
      case 'next':
        goNext();
        break;
      case 'prev':
        goPrev();
        break;
      case 'skip':
        goSkip();
        break;
      case 'flag':
        goFlag();
        break;
      case 'zoom-in':
        zoomBy(1.25);
        break;
      case 'zoom-out':
        zoomBy(0.8);
        break;
      case 'zoom-fit':
        resetZoom();
        break;
      case 'zoom-full':
        zoomFull();
        break;
      case 'lightbox': {
        const stage = el.closest('.stage');
        const image = stage && stage.querySelector('img');
        if (image) openLightbox(image.src);
        break;
      }
      case 'swap': {
        const task = store.currentTask();
        if (!task || task.mode !== 'pairwise') break;
        const ann = store.ensureAnn(task);
        const voted = Object.keys(ann.verdicts || {}).length;
        if (
          voted &&
          !window.confirm(
            `本题已经投了 ${voted} 项判定。\n交换左右会清空这些判定（否则记录里的显示顺序会对不上），继续？`
          )
        ) {
          break;
        }
        const result = store.swapOrder();
        render();
        toast(result.cleared ? '已交换左右，本题判定已清空' : '已交换左右');
        break;
      }
      case 'do-import':
        doImport();
        break;
      case 'switch-annotator':
        switchAnnotator();
        break;
      case 'save-annotator':
        saveAnnotator();
        break;
      case 'restore-labels':
        restoreLabels();
        break;
      case 'export-verdicts':
        doExport('verdicts');
        break;
      case 'export-consistency':
        doExport('consistency');
        break;
      case 'export-summary':
        doExport('summary');
        break;
      case 'jump-task':
        jumpTask(el.dataset.task);
        break;
      case 'reset':
        resetLocal();
        break;
      case 'reset-annotations':
        resetAnnotations();
        break;
      default:
        break;
    }
  }

  /* ------------------------------------------------------------------ 事件 */
  function bindStatic() {
    document.addEventListener('click', (e) => {
      const jump = e.target.closest('[data-jump]');
      if (jump) {
        state.idx = Number(jump.dataset.jump);
        state.showSummary = false;
        render();
        return;
      }

      const modeBtn = e.target.closest('.tab[data-mode], [data-mode]');
      if (modeBtn && modeBtn.dataset.mode) {
        if (!state.tasks.length) return;
        const mode = modeBtn.dataset.mode;
        if (state.mode === mode && !state.showSummary) return;
        store.setMode(mode);
        render();
        return;
      }

      const vote = e.target.closest('[data-vote]');
      if (vote) {
        const task = store.currentTask();
        const host = vote.closest('[data-dim], [data-crit]');
        if (task && host) {
          const id = host.dataset.dim || host.dataset.crit;
          store.setVote(task, id, vote.dataset.vote === '1');
          refreshVerdict(id);
          updateActionState();
          maybeAutoNext();
          vote.blur();
        }
        return;
      }

      const corr = e.target.closest('[data-corr]');
      if (corr) {
        const wrap = corr.closest('[data-correction]');
        const task = store.currentTask();
        if (task && wrap) {
          store.setCorrection(task, wrap.dataset.correction, corr.dataset.corr);
          refreshVerdict(wrap.dataset.correction);
        }
        corr.blur();
        return;
      }

      const overall = e.target.closest('[data-overall]');
      if (overall) {
        const task = store.currentTask();
        if (task) {
          store.setOverall(task, overall.dataset.overall);
          $$('[data-overall]').forEach((button) =>
            button.classList.toggle(
              'active',
              button.dataset.overall === store.ensureAnn(task).overall
            )
          );
        }
        overall.blur();
        return;
      }

      const action = e.target.closest('[data-act]');
      if (action) {
        handleAction(action.dataset.act, action);
        return;
      }

      if (e.target === scrim) closeSettings(true);
      if (e.target === overlay || (e.target.classList && e.target.classList.contains('lightbox'))) {
        closeOverlay();
      }
    });

    document.addEventListener('input', (e) => {
      const note = e.target.closest('#noteInput');
      if (note) {
        const task = store.currentTask();
        if (task) store.setNote(task, note.value);
        return;
      }
      const labelInput = e.target.closest('[data-label-input]');
      if (labelInput) {
        const id = labelInput.dataset.labelInput;
        state.config.labels[id] = labelInput.value;
        $$(`[data-dim-label="${id}"], [data-crit-label="${id}"]`).forEach((el) => {
          el.textContent = labelInput.value || id;
        });
        return;
      }
      const questionInput = e.target.closest('[data-question-input]');
      if (questionInput) {
        state.config.questions[questionInput.dataset.questionInput] = questionInput.value;
      }
    });

    document.addEventListener('change', (e) => {
      const exportSelect = e.target.closest('#exportAnnotator');
      if (exportSelect) {
        state.exportAnnotator = exportSelect.value;
        const stem = `${state.dataset.name || 'dataset'}${
          state.exportAnnotator ? `-${state.exportAnnotator}` : ''
        }`;
        const hint = $('#exportFileHint');
        if (hint) {
          hint.innerHTML = `文件名以 <code>${esc(stem)}</code> 开头${
            state.exportAnnotator ? ' · 单人导出时 κ 为空' : ''
          }`;
        }
        const sub = overlay.querySelector('.sub');
        if (sub) {
          sub.innerHTML = state.exportAnnotator
            ? `仅导出标注员 <b>${esc(state.exportAnnotator)}</b> 的标注`
            : '从服务器数据目录导出（包含所有标注员）';
        }
        return;
      }
      const select = e.target.closest('[data-corr-select]');
      if (select) {
        const task = store.currentTask();
        if (task) {
          store.setCorrection(task, select.dataset.corrSelect, select.value);
          refreshVerdict(select.dataset.corrSelect);
        }
        return;
      }
      const toggle = e.target.closest('[data-toggle]');
      if (toggle) {
        state.config[toggle.dataset.toggle] = toggle.checked;
        store.savePreferences();
        if (toggle.dataset.toggle === 'showRationale') render();
      }
    });

    const datasetSelect = $('#datasetSelect');
    datasetSelect.addEventListener('change', async () => {
      const name = datasetSelect.value;
      if (!name || name === state.dataset.name) return;
      state.busy = true;
      state.showSummary = false;
      render();
      try {
        await store.loadDataset(name);
      } catch (err) {
        toast(`加载失败：${err.message}`);
      } finally {
        state.busy = false;
        render();
      }
    });

    document.addEventListener('keydown', (e) => {
      const drawerOpen = drawer.classList.contains('open');
      const overlayOpen = !overlay.hidden;
      if (drawerOpen || overlayOpen) {
        if (e.key === 'Escape') closeAll();
        return;
      }
      const tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') {
        if (e.key === 'Escape') e.target.blur();
        return;
      }
      if (e.key === '?') {
        e.preventDefault();
        openHelp();
        return;
      }
      if (e.key === 'Escape') {
        if (state.showSummary) {
          state.showSummary = false;
          render();
        }
        return;
      }
      if (state.showSummary || !state.tasks.length) return;
      if (e.key === 'Enter' && e.target.closest('button')) return;

      const task = store.currentTask();
      if (!task) return;
      const digit = e.code && /^Digit([1-9])$/.exec(e.code);
      if (digit && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const index = Number(digit[1]) - 1;
        const ids = CV.model.itemIds(task);
        if (index < ids.length) {
          e.preventDefault();
          store.setVote(task, ids[index], !e.shiftKey);
          refreshVerdict(ids[index]);
          updateActionState();
          maybeAutoNext();
        }
        return;
      }
      switch (e.key) {
        case 'Enter':
        case 'ArrowRight':
          e.preventDefault();
          goNext();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          goPrev();
          break;
        case 's':
        case 'S':
          goSkip();
          break;
        case 'f':
        case 'F':
          goFlag();
          break;
        case 'u':
        case 'U':
          goUndo();
          break;
        case 'z':
        case 'Z':
          if (zoom.scale > 1.05) resetZoom();
          else zoomFull();
          break;
        default:
          break;
      }
    });

    document.addEventListener('cv:save', updateSaveIndicator);

    document.addEventListener(
      'error',
      (e) => {
        const image = e.target;
        if (image && image.tagName === 'IMG') image.classList.add('broken');
      },
      true
    );
  }

  function toast(message) {
    toastEl.textContent = message;
    toastEl.hidden = false;
    requestAnimationFrame(() => toastEl.classList.add('show'));
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      toastEl.classList.remove('show');
      setTimeout(() => {
        if (!toastEl.classList.contains('show')) toastEl.hidden = true;
      }, 220);
    }, 2400);
  }

  /* ------------------------------------------------------------------ 启动 */
  async function start() {
    bindStatic();
    try {
      await store.boot();
    } catch (err) {
      console.error(err);
      toast(`后端不可用，已切到演示数据：${err.message}`);
      store.useDemo();
    }
    const params = query();
    if (params.get('i') != null) {
      const index = Number(params.get('i'));
      if (Number.isFinite(index)) {
        const list = store.tasksFor(state.mode);
        state.idx = clamp(index, 0, Math.max(0, list.length - 1));
      }
    }
    if (state.source === 'server' && !state.annotatorChosen && state.tasks.length) {
      render();
      openAnnotator();
      return;
    }
    if (params.get('summary') === '1') {
      openSummary();
    } else {
      render();
      if (params.get('settings') === '1') setTimeout(openSettings, 60);
      if (params.get('import') === '1') setTimeout(openImport, 60);
      if (params.get('export') === '1') setTimeout(openExport, 60);
    }
  }

  start();

  window.CV.app = { render, openSummary, openSettings, openImport, openExport, toast };

  /* 控制台接口（README 里写过、但之前一直没实现）：改完顺手重绘一次。 */
  window.CV.getConfig = () => store.state.config;
  window.CV.getAnnotations = () => Object.values(store.state.annotations);
  window.CV.setLabels = async (labels, questions) => {
    await store.setLabels(labels || {}, questions || {});
    render();
    return store.state.config;
  };
  window.CV.setQuestions = async (questions) => {
    await store.setLabels({}, questions || {});
    render();
    return store.state.config;
  };
  window.CV.deleteAnnotations = async ({ annotator = store.state.annotator, taskId } = {}) => {
    const result = await CV.api.deleteAnnotations(store.state.dataset.name, { annotator, taskId });
    await store.setAnnotator(store.state.annotator);
    render();
    return result;
  };
})(window.CV);
