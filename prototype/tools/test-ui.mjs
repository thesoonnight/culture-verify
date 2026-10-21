/**
 * 浏览器冒烟测试（CDP）。
 *
 * 前置：
 *   python server.py serve --port 8766
 *   chrome --headless=new --remote-debugging-port=9334 http://127.0.0.1:8766/
 *   node tools/test-ui.mjs
 */
const PORT = process.env.CDP_PORT || 9334;
const BASE = process.env.CV_URL || 'http://127.0.0.1:8766';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let failures = 0;
const errors = [];

function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok || !extra ? '' : '  →  ' + extra}`);
  if (!ok) failures += 1;
}

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page');
if (!page) throw new Error('没有可用的页面 target');

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve);
  ws.addEventListener('error', reject);
});

let seq = 0;
const pending = new Map();
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
  if (msg.method === 'Runtime.exceptionThrown') {
    errors.push(msg.params.exceptionDetails.text + ' ' + (msg.params.exceptionDetails.exception?.description || ''));
  }
});

function send(method, params = {}) {
  return new Promise((resolve) => {
    const id = ++seq;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function js(expression) {
  const r = await send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (r.result && r.result.exceptionDetails) {
    throw new Error(JSON.stringify(r.result.exceptionDetails));
  }
  return r.result && r.result.result ? r.result.result.value : undefined;
}

async function nav(url) {
  await send('Page.navigate', { url });
  await sleep(1600);
}

async function click(selector) {
  const ok = await js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.click(); return true; })()`);
  if (!ok) throw new Error('找不到元素 ' + selector);
  await sleep(250);
}

await send('Runtime.enable');
await send('Page.enable');

/* ------------------------------------------------------------ 服务器模式 */
await nav(`${BASE}/?annotator=qa&dataset=demo`);
check('server mode loads dataset', (await js(`document.querySelector('#datasetSelect').value`)) === 'demo');
check('counter is 1 / 6', (await js(`document.querySelector('#counter').textContent.trim()`)) === '1 / 6');
check('three evaluator items render', (await js(`document.querySelectorAll('.eval-item').length`)) === 3);

await click('.eval-item[data-dim="d1"] [data-vote="1"]');
check('agree paints row', await js(`document.querySelector('.eval-item[data-dim="d1"]').classList.contains('is-agree')`));
await sleep(600);
check('save indicator turns saved', await js(`document.querySelector('#saveState').classList.contains('saved')`));

const stored = await js(`fetch('/api/datasets/demo/annotations?annotator=qa').then(r => r.json()).then(d => d.annotations)`);
check('annotation reached the server', Array.isArray(stored) && stored.length === 1 && stored[0].verdicts.d1.agree === true);

await nav(`${BASE}/?annotator=qa&dataset=demo`);
check('annotation survives reload', await js(`document.querySelector('.eval-item[data-dim="d1"]').classList.contains('is-agree')`));

await click('[data-act="settings"]');
check('settings drawer opens', await js(`document.querySelector('#drawer').classList.contains('open')`));
await js(`(() => { const input = document.querySelector('[data-label-input="d1"]'); input.value = '测试维度名'; input.dispatchEvent(new Event('input', { bubbles: true })); })()`);
await click('[data-act="close-drawer"]');
await sleep(700);
const config = await js(`fetch('/api/datasets/demo/tasks').then(r => r.json()).then(d => d.config)`);
check('dimension rename persisted', config.dimensions.find((d) => d.id === 'd1')?.label === '测试维度名');
check('visible label updated', (await js(`document.querySelector('[data-dim-label="d1"]').textContent`)) === '测试维度名');

await click('.tab[data-mode="pairwise"]');
check('pairwise tab loads', (await js(`document.querySelector('#counter').textContent.trim()`)) === '1 / 3');
check('two criteria rows', (await js(`document.querySelectorAll('.crit-row').length`)) === 2);
await click('.crit-row[data-crit="q1"] [data-vote="0"]');
await js(`(() => { const sel = document.querySelector('[data-corr-select="q1"]'); sel.value = 'gap'; sel.dispatchEvent(new Event('change', { bubbles: true })); })()`);
await click('[data-overall="A"]');
await sleep(500);
const pairAnn = await js(`fetch('/api/datasets/demo/annotations?annotator=qa').then(r => r.json()).then(d => d.annotations.find(a => a.mode === 'pairwise'))`);
check('pairwise correction saved', pairAnn && pairAnn.verdicts.q1.correction === 'gap');
check('pairwise overall saved', pairAnn && pairAnn.overall === 'A');

await click('[data-act="summary"]');
await sleep(1200);
check('summary renders', await js(`!!document.querySelector('.summary')`));
check('summary has four stat cards', (await js(`document.querySelectorAll('.stat-card').length`)) === 4);
check('summary has inter-annotator block', await js(`!!document.querySelector('.inter-grid')`));
check('summary has dimension bars', (await js(`document.querySelectorAll('.bar-row').length`)) >= 2);

const verdictsCsv = await js(`fetch('/api/datasets/demo/export?kind=verdicts').then(r => r.text())`);
check('verdicts CSV has header', verdictsCsv.includes('task_id,mode,annotator'));
const consistencyCsv = await js(`fetch('/api/datasets/demo/export?kind=consistency').then(r => r.text())`);
check('consistency CSV has kappa column', consistencyCsv.includes('kappa'));

await click('[data-act="export"]');
await sleep(500);
check(
  'export modal lists annotators',
  (await js(`document.querySelectorAll('#exportAnnotator option').length`)) >= 2
);
await js(`(() => {
  const sel = document.querySelector('#exportAnnotator');
  sel.value = 'qa';
  sel.dispatchEvent(new Event('change', { bubbles: true }));
})()`);
check(
  'export annotator filter is stored',
  (await js(`window.CV.store.state.exportAnnotator`)) === 'qa'
);
await click('[data-act="close-overlay"]');

/* --------------------------------------------------------------- 本地模式 */
await nav(`${BASE}/?demo=1`);
check('local demo mode', await js(`document.querySelector('#datasetPicker').classList.contains('is-local')`));
check('local counter is 1 / 6', (await js(`document.querySelector('#counter').textContent.trim()`)) === '1 / 6');
await click('.eval-item[data-dim="d1"] [data-vote="1"]');
check(
  'local annotation stored',
  await js(`(() => { const raw = localStorage.getItem('culture-verify-v02'); if (!raw) return false; const data = JSON.parse(raw); return data.annotations['pointwise:A01'].verdicts.d1.agree === true; })()`)
);
await nav(`${BASE}/?demo=1`);
check('local annotation survives reload', await js(`document.querySelector('.eval-item[data-dim="d1"]').classList.contains('is-agree')`));

await click('[data-act="help"]');
check('help modal opens', await js(`!document.querySelector('#overlay').hidden`));
await click('[data-act="close-overlay"]');
check('help modal closes', await js(`document.querySelector('#overlay').hidden`));

await click('[data-act="summary"]');
await sleep(500);
check('local summary renders', await js(`!!document.querySelector('.summary')`));

await js(`window.confirm = () => true; document.querySelector('[data-act="reset"]').click()`);
await sleep(400);
check('local reset clears storage', (await js(`localStorage.getItem('culture-verify-v02')`)) === null);

/* --------------------------------------------------- 0.2.1 修复项回归 */
await nav(`${BASE}/?annotator=qa&dataset=demo`);
check('CV.setLabels 真的存在（README 契约）', (await js(`typeof window.CV.setLabels`)) === 'function');
check(
  'CV.getConfig 能读出维度名',
  (await js(`(window.CV.getConfig().labels || {}).d1 || ''`)) !== ''
);

await click('.tab[data-mode="pairwise"]');
await js(`(() => {
  const st = window.CV.store.state;
  const index = st.tasks.filter((t) => t.mode === 'pairwise').findIndex((t) => t.id === 'B03');
  st.idx = index < 0 ? 0 : index;
  window.CV.app.render();
})()`);
const shownBefore = await js(`window.CV.store.ensureAnn(window.CV.store.currentTask()).shown_as`);
await js(`(() => { window.confirm = () => true; document.querySelector('[data-act="swap"]').click(); })()`);
await sleep(600);
const shownAfter = await js(`window.CV.store.ensureAnn(window.CV.store.currentTask()).shown_as`);
check('交换左右会同时改写 shown_as', shownBefore !== shownAfter, `${shownBefore} → ${shownAfter}`);
const shownStored = await js(
  `fetch('/api/datasets/demo/annotations?annotator=qa').then((r) => r.json()).then((d) => (d.annotations.find((a) => a.task_id === 'B03') || {}).shown_as)`
);
check('交换后的顺序落到了服务器', shownStored === shownAfter, String(shownStored));

const deletedCount = await js(`(async () => {
  await fetch('/api/datasets/demo/annotations?annotator=qa&task_id=B03', { method: 'DELETE' });
  const rest = await fetch('/api/datasets/demo/annotations?annotator=qa').then((r) => r.json());
  return rest.annotations.filter((a) => a.task_id === 'B03').length;
})()`);
check('DELETE 能删掉单条标注', deletedCount === 0, String(deletedCount));

check('no uncaught page exceptions', errors.length === 0, errors.join(' | '));

ws.close();
console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
