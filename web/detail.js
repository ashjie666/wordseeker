/* ==========================================================================
   WordSeeker · 关键词详情页
   数据：web/data/series.json（file:// 下回退到 data/series.js 的 window.WS_SERIES）
   ========================================================================== */

'use strict';

(function () {
  const params = new URLSearchParams(window.location.search);
  const term = params.get('term');
  const state = { window: 'realtime' };
  let DATA = null;
  let ITEM = null;

  const CATEGORY_LABEL = { game: '游戏', travel: '旅游', culture: '文化', tech: '科技', life: '生活' };
  const GAME_TYPE_LABEL = { acg: '二次元', rpg: 'RPG', slg: '策略', fps: '射击', mobile: '手游' };

  function chip(label, active, onClick) {
    return WS.el('button', {
      class: 'chip', type: 'button',
      'aria-pressed': active ? 'true' : 'false',
      onclick: onClick, text: label,
    });
  }

  function renderHero() {
    const host = WS.$('detail-hero');
    host.innerHTML = '';
    if (!ITEM) {
      host.append(WS.el('h2', { class: 'detail-term', text: '未指定关键词' }));
      host.append(WS.el('span', { class: 'detail-cn', text: '从下方列表选择一个关键词查看详情。' }));
      return;
    }
    const tags = [];
    if (ITEM.category) tags.push(CATEGORY_LABEL[ITEM.category] || ITEM.category);
    if (ITEM.game_type) tags.push(GAME_TYPE_LABEL[ITEM.game_type] || ITEM.game_type);
    if (ITEM.studio) tags.push(ITEM.studio);

    host.append(WS.el('h2', { class: 'detail-term', text: ITEM.term }));
    if (ITEM.cn) host.append(WS.el('span', { class: 'detail-cn', text: ITEM.cn }));
    host.append(WS.el('div', { class: 'detail-tags', html: tags.map(function (tag) {
      return '<span class="tag">' + WS.escapeHtml(tag) + '</span>';
    }).join('') }));
  }

  function renderWindowTabs() {
    const box = WS.$('window-tabs');
    box.innerHTML = '';
    (DATA.windows || []).forEach(function (item) {
      box.append(chip(item.label, state.window === item.id, function () {
        state.window = item.id;
        renderWindowTabs();
        renderChart();
      }));
    });
  }

  function renderChart() {
    if (!ITEM) return;
    const points = (ITEM.windows || {})[state.window] || [];
    WS.$('trend-chart').innerHTML = points.length
      ? WS.lineChart([{ name: ITEM.term, color: 'var(--brand)', points: points }], {})
      : '<p class="metric-note">该窗口暂无序列数据。</p>';
    WS.$('trend-sub').textContent = '窗口 ' + state.window + ' · 相对热度指数 0-100';
  }

  function renderGeo() {
    const grid = WS.$('geo-grid');
    grid.innerHTML = '';
    const items = ITEM.geo || [];
    if (!items.length) {
      grid.append(WS.el('p', { class: 'metric-note', text: '暂无地域数据。' }));
      return;
    }
    items.forEach(function (entry) {
      grid.append(WS.el('div', { class: 'geo-card' }, [
        WS.el('div', { class: 'geo-card-head' }, [
          WS.el('span', { text: entry.label }),
          WS.el('span', { class: 'geo-value', text: String(entry.value) }),
        ]),
        WS.el('div', { class: 'geo-bar', html: '<i style="width:' + entry.value + '%"></i>' }),
      ]));
    });
  }

  function renderRelated() {
    const related = ITEM.related || {};
    const risingHost = WS.$('related-rising');
    const topHost = WS.$('related-top');
    risingHost.innerHTML = '';
    topHost.innerHTML = '';

    function fill(host, rows, isRising) {
      if (!rows || !rows.length) {
        host.append(WS.el('p', { class: 'metric-note', text: '暂无数据。' }));
        return;
      }
      rows.slice(0, 12).forEach(function (row) {
        const value = (row.value === null || row.value === undefined)
          ? '—'
          : (isRising ? '+' + row.value + '%' : String(row.value));
        host.append(WS.el('div', { class: 'related-row' }, [
          WS.el('span', { class: 'related-query', text: row.query }),
          WS.el('span', {
            class: 'related-value' + (isRising ? ' related-value-rising' : ''),
            text: value,
          }),
        ]));
      });
    }

    fill(risingHost, related.rising, true);
    fill(topHost, related.top, false);
  }

  function renderLinks() {
    const host = WS.$('link-grid');
    host.innerHTML = '';
    (ITEM.links || []).forEach(function (link) {
      host.append(WS.el('a', { class: 'link-chip', href: link.url, target: '_blank', rel: 'noopener',
        text: link.label + ' ↗' }));
    });
  }

  function renderPicker() {
    const panel = WS.$('picker-panel');
    const box = WS.$('term-picker');
    const terms = Object.keys(DATA.items || {});
    panel.hidden = !!ITEM;
    if (!terms.length) {
      box.append(WS.el('p', { class: 'metric-note', text: '暂无可用关键词。' }));
      return;
    }
    box.innerHTML = '';
    terms.forEach(function (name) {
      const meta = DATA.items[name];
      box.append(WS.el('a', {
        class: 'chip', href: 'detail.html?term=' + encodeURIComponent(name),
        text: name + (meta.cn ? ' · ' + meta.cn : ''), style: 'text-decoration:none',
      }));
    });
  }

  function showPanels(visible) {
    ['trend-panel', 'geo-panel', 'related-panel', 'links-panel'].forEach(function (id) {
      WS.$(id).hidden = !visible;
    });
  }

  async function boot() {
    WS.initPage();
    try {
      DATA = await WS.loadData('series', 'WS_SERIES');
    } catch (error) {
      WS.$('detail-hero').innerHTML = '<p class="metric-note">数据还没生成。请先运行采集：<code>python -m collector.main</code></p>';
      return;
    }
    WS.renderMeta(DATA.meta || {});

    ITEM = term ? (DATA.items || {})[term] : null;
    renderHero();
    renderPicker();

    if (!ITEM) {
      showPanels(false);
      return;
    }

    const windows = DATA.windows || [];
    if (windows.length) state.window = windows[0].id;
    document.title = ITEM.term + ' · 热度详情 · WordSeeker';

    showPanels(true);
    renderWindowTabs();
    renderChart();
    renderGeo();
    renderRelated();
    renderLinks();
  }

  boot();
})();
