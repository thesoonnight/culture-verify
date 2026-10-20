/* 小工具：DOM、转义、CSV、下载、时间。 */
window.CV = window.CV || {};
(function (CV) {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const nowISO = () => new Date().toISOString();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (value) =>
    String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ESCAPES[char]);

  function hashStr(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function fmtPct(value) {
    return value == null || Number.isNaN(value) ? '—' : `${Math.round(value * 100)}%`;
  }

  function fmtSec(ms) {
    return ms == null ? '—' : `${(ms / 1000).toFixed(1)} s`;
  }

  function debounce(fn, wait) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  }

  function csvCell(value) {
    if (value == null) return '';
    const text = String(value);
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function toCSV(rows, columns) {
    const cols = columns || (rows.length ? Object.keys(rows[0]) : []);
    const lines = [cols.map(csvCell).join(',')];
    rows.forEach((row) => lines.push(cols.map((col) => csvCell(row[col])).join(',')));
    return `\uFEFF${lines.join('\r\n')}`;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function downloadText(text, filename, type = 'text/plain;charset=utf-8') {
    downloadBlob(new Blob([text], { type }), filename);
  }

  function query() {
    return new URLSearchParams(location.search);
  }

  CV.utils = {
    $,
    $$,
    clamp,
    nowISO,
    sleep,
    esc,
    hashStr,
    fmtPct,
    fmtSec,
    debounce,
    toCSV,
    downloadBlob,
    downloadText,
    query,
  };
})(window.CV);
