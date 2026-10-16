/* ==========================================================================
   WordSeeker · 共享前端层
   数据加载（json 优先、file:// 回退到内联 js 全局变量）、主题、迷你走势图、折线图
   ========================================================================== */

'use strict';

const WS = (function () {
  const THEME_KEY = 'wordseeker:theme';

  /* ---------- DOM helpers ---------- */

  function $(id) { return document.getElementById(id); }

  function el(tag, props, children) {
    const node = document.createElement(tag);
    const settings = props || {};
    for (const key in settings) {
      const value = settings[key];
      if (value === null || value === undefined) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'html') node.innerHTML = value;
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
      else node.setAttribute(key, value);
    }
    for (const child of children || []) {
      if (child === null || child === undefined || child === false) continue;
      node.append(typeof child === 'string' ? document.createTextNode(child) : child);
    }
    return node;
  }

  function escapeHtml(text) {
    return String(text === null || text === undefined ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function pad2(value) { return String(value).padStart(2, '0'); }

  /* ---------- 主题 ---------- */

  function bindThemeToggle() {
    const button = $('theme-toggle');
    if (!button) return;
    button.addEventListener('click', function () {
      const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      const next = current === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem(THEME_KEY, next); } catch (error) { /* 隐私模式下忽略 */ }
    });
  }

  /* ---------- 数据加载 ---------- */

  async function loadData(name, globalName) {
    try {
      const response = await fetch('data/' + name + '.json', { cache: 'no-store' });
      if (response.ok) return await response.json();
    } catch (error) {
      /* file:// 下 fetch 必然失败，回退到内联数据 */
    }
    if (window[globalName]) return window[globalName];
    throw new Error('无法加载数据：' + name);
  }

  /* ---------- 元信息 ---------- */

  function renderMeta(meta) {
    const chip = $('updated-at');
    if (chip) chip.textContent = '数据更新于 ' + (meta.generated_at_cst || '—') + ' (CST)';

    const banner = $('mode-banner');
    if (!banner) return;
    const isSample = meta.data_mode === 'sample';
    banner.className = 'mode-banner' + (isSample ? '' : ' mode-banner-live');
    banner.innerHTML = isSample
      ? '<strong>示例数据</strong> 当前未接入真实 Google Trends（' + escapeHtml(meta.backend) +
        ' 后端），展示的是合成数据，仅用于验证界面与交互；配置 SERPAPI_KEY 或代理后自动切换为真实数据。'
      : '<strong>实时数据</strong> 由 ' + escapeHtml(meta.backend) +
        ' 抓取 Google Trends（窗口 ' + escapeHtml(meta.window) + '），更新于 ' +
        escapeHtml(meta.generated_at_cst) + ' (CST)。';
    banner.hidden = false;
  }

  /* ---------- 趋势箭头 ---------- */

  function deltaHtml(row) {
    const rank = row.d;
    const percent = row.p;
    let cls = 'delta-flat';
    let arrow = '—';
    let title = '与上期相比持平';
    if (rank === null || rank === undefined) {
      return '<span class="delta delta-flat" title="缺少上期快照，暂无法比较">— 新</span>';
    }
    if (rank > 0) { cls = 'delta-up'; arrow = '↑' + rank; title = '较上期上升 ' + rank + ' 位'; }
    else if (rank < 0) { cls = 'delta-down'; arrow = '↓' + Math.abs(rank); title = '较上期下降 ' + Math.abs(rank) + ' 位'; }
    const pct = (percent === null || percent === undefined)
      ? ''
      : '<span class="delta-pct">' + (percent > 0 ? '+' : '') + percent + '%</span>';
    return '<span class="delta ' + cls + '" title="' + title + '">' + arrow + '</span>' + pct;
  }

  /* ---------- 迷你走势图 ---------- */

  function sparkline(values) {
    if (!values || values.length < 2) return '<span class="spark-empty">—</span>';
    const width = 92;
    const height = 26;
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const span = (max - min) || 1;
    const stepX = width / (values.length - 1);
    const points = values.map(function (value, index) {
      return [index * stepX, height - 2 - ((value - min) / span) * (height - 4)];
    });
    const line = points.map(function (point, index) {
      return (index ? 'L' : 'M') + point[0].toFixed(1) + ' ' + point[1].toFixed(1);
    }).join(' ');
    const area = line + ' L' + width + ' ' + height + ' L0 ' + height + ' Z';
    return '<svg class="spark" viewBox="0 0 ' + width + ' ' + height +
      '" preserveAspectRatio="none" aria-hidden="true">' +
      '<path class="spark-area" d="' + area + '"/>' +
      '<path class="spark-line" d="' + line + '"/></svg>';
  }

  const PALETTE = ['var(--brand)', 'var(--blue)', 'var(--amber)', 'var(--violet)', 'var(--pink)'];

  /* ---------- 折线图 ---------- */

  function fmtTick(milliseconds, spanMs) {
    const date = new Date(milliseconds);
    if (spanMs <= 48 * 3600 * 1000) {
      return pad2(date.getMonth() + 1) + '-' + pad2(date.getDate()) + ' ' + pad2(date.getHours()) + 'h';
    }
    return pad2(date.getMonth() + 1) + '-' + pad2(date.getDate());
  }

  function lineChart(seriesList, options) {
    const opts = options || {};
    const width = 880;
    const height = 260;
    const padLeft = 36;
    const padRight = 14;
    const padTop = 12;
    const padBottom = 26;
    const plotWidth = width - padLeft - padRight;
    const plotHeight = height - padTop - padBottom;

    const usable = (seriesList || []).filter(function (item) { return item.points && item.points.length; });
    if (!usable.length) return '<p class="metric-note">暂无序列数据。</p>';

    const stamps = [];
    usable.forEach(function (item) {
      item.points.forEach(function (point) { stamps.push(+new Date(point[0])); });
    });
    const minTime = Math.min.apply(null, stamps);
    const maxTime = Math.max.apply(null, stamps);
    const spanTime = (maxTime - minTime) || 1;

    const x = function (milliseconds) { return padLeft + ((milliseconds - minTime) / spanTime) * plotWidth; };
    const y = function (value) { return padTop + (1 - Math.max(0, Math.min(100, value)) / 100) * plotHeight; };

    const parts = [];
    [100, 75, 50, 25, 0].forEach(function (value) {
      const position = y(value);
      parts.push('<line x1="' + padLeft + '" y1="' + position.toFixed(1) + '" x2="' + (width - padRight) +
        '" y2="' + position.toFixed(1) + '"/>');
      parts.push('<text class="chart-axis" x="' + (padLeft - 8) + '" y="' + (position + 3.5).toFixed(1) +
        '" text-anchor="end">' + value + '</text>');
    });

    [0, 0.5, 1].forEach(function (ratio) {
      const stamp = minTime + spanTime * ratio;
      parts.push('<text class="chart-axis" x="' + x(stamp).toFixed(1) + '" y="' + (height - 8) +
        '" text-anchor="' + (ratio === 0 ? 'start' : ratio === 1 ? 'end' : 'middle') + '">' +
        fmtTick(stamp, spanTime) + '</text>');
    });

    usable.forEach(function (item, index) {
      const color = item.color || PALETTE[index % PALETTE.length];
      const path = item.points.map(function (point, pointIndex) {
        return (pointIndex ? 'L' : 'M') + x(+new Date(point[0])).toFixed(1) + ' ' + y(point[1]).toFixed(1);
      }).join(' ');
      parts.push('<path d="' + path + '" fill="none" stroke="' + color + '" stroke-width="2" ' +
        'stroke-linejoin="round" stroke-linecap="round"/>');
      if (opts.dots !== false) {
        const last = item.points[item.points.length - 1];
        parts.push('<circle cx="' + x(+new Date(last[0])).toFixed(1) + '" cy="' + y(last[1]).toFixed(1) +
          '" r="3" fill="' + color + '"/>');
      }
    });

    return '<svg class="chart" viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="热度走势折线图">' +
      '<g class="chart-grid">' + parts.slice(0, 10).join('') + '</g>' +
      '<g>' + parts.slice(10).join('') + '</g></svg>';
  }

  /* ---------- 页面通用初始化 ---------- */

  function initPage() {
    bindThemeToggle();
    document.querySelectorAll('.year').forEach(function (node) {
      node.textContent = new Date().getFullYear();
    });
  }

  return {
    $: $, el: el, escapeHtml: escapeHtml, pad2: pad2,
    bindThemeToggle: bindThemeToggle, loadData: loadData, renderMeta: renderMeta,
    deltaHtml: deltaHtml, sparkline: sparkline, lineChart: lineChart,
    palette: PALETTE, initPage: initPage,
  };
})();
