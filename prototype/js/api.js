/* 服务器 API 适配层；探不到后端时自动退回本地演示模式。 */
window.CV = window.CV || {};
(function (CV) {
  'use strict';

  async function parseError(res) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      message = data.error || message;
      if (Array.isArray(data.messages) && data.messages.length) {
        message += `：${data.messages[0]}`;
      }
    } catch (err) {
      /* 非 JSON 错误 */
    }
    return message;
  }

  async function requestJSON(url, options = {}) {
    const res = await fetch(url, { cache: 'no-store', ...options });
    if (!res.ok) throw new Error(await parseError(res));
    const type = res.headers.get('content-type') || '';
    if (!type.includes('json')) return res.text();
    return res.json();
  }

  async function probe() {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 1500);
      const res = await fetch('/api/health', { cache: 'no-store', signal: controller.signal });
      clearTimeout(timer);
      if (!res.ok) return false;
      const data = await res.json();
      return !!data.ok;
    } catch (err) {
      return false;
    }
  }

  const api = {
    mode: 'local',

    async boot() {
      this.mode = (await probe()) ? 'server' : 'local';
      return this.mode;
    },

    async listDatasets() {
      const data = await requestJSON('/api/datasets');
      return data.datasets || [];
    },

    async loadDataset(name) {
      return requestJSON(`/api/datasets/${encodeURIComponent(name)}/tasks`);
    },

    async getAnnotations(name, annotator) {
      const suffix = annotator ? `?annotator=${encodeURIComponent(annotator)}` : '';
      const data = await requestJSON(`/api/datasets/${encodeURIComponent(name)}/annotations${suffix}`);
      return data.annotations || [];
    },

    async saveAnnotation(name, annotation) {
      return requestJSON(`/api/datasets/${encodeURIComponent(name)}/annotations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ annotation }),
        keepalive: true,
      });
    },

    async updateConfig(name, labels, questions) {
      const data = await requestJSON(`/api/datasets/${encodeURIComponent(name)}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ labels, questions }),
      });
      return data.config || {};
    },

    async deleteAnnotations(name, { annotator, taskId } = {}) {
      const params = new URLSearchParams();
      if (annotator) params.set('annotator', annotator);
      if (taskId) params.set('task_id', taskId);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      return requestJSON(`/api/datasets/${encodeURIComponent(name)}/annotations${suffix}`, {
        method: 'DELETE',
      });
    },

    async deleteDataset(name) {
      return requestJSON(`/api/datasets/${encodeURIComponent(name)}`, { method: 'DELETE' });
    },

    async stats(name, annotator) {
      const suffix = annotator ? `?annotator=${encodeURIComponent(annotator)}` : '';
      return requestJSON(`/api/datasets/${encodeURIComponent(name)}/stats${suffix}`);
    },

    async importZip(name, file, { title = '', overwrite = false } = {}) {
      const params = new URLSearchParams({ name, title: title || '', overwrite: overwrite ? '1' : '0' });
      return requestJSON(`/api/datasets/import?${params.toString()}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/zip' },
        body: file,
      });
    },

    exportUrl(name, kind, annotator) {
      const params = new URLSearchParams({ kind });
      if (annotator) params.set('annotator', annotator);
      return `/api/datasets/${encodeURIComponent(name)}/export?${params.toString()}`;
    },
  };

  CV.api = api;
})(window.CV);
