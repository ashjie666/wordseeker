/* ==========================================================================
   WordSeeker · 首页（通用热搜榜）
   数据：web/data/trending.json（file:// 下回退到 data/trending.js 的 window.WS_TRENDING）
   ========================================================================== */

'use strict';

(function () {
  const state = { region: 'world', category: 'all', query: '' };
  let DATA = null;
  let CATEGORY_LABEL = {};
  const TOP_N = 50;

  function chip(label, active, onClick) {
    return WS.el('button', {
      class: 'chip', type: 'button',
      'aria-pressed': active ? 'true' : 'false',
      onclick: onClick, text: label,
    });
  }

  function metaOf(term) { return DATA.terms[term] || {}; }

  function categoryLabel(id) {
    return CATEGORY_LABEL[id] || id;
  }

  /* ---------- 筛选器 ---------- */

  function renderRegionChips() {
    const box = WS.$('filter-region');
    box.innerHTML = '';
    DATA.regions.forEach(function (region) {
      box.append(chip(region.label, state.region === region.id, function () {
        state.region = region.id;
        renderAll();
      }));
    });
  }

  function renderCategoryChips() {
    const box = WS.$('filter-category');
    box.innerHTML = '';
    DATA.categories.forEach(function (category) {
      box.append(chip(category.label, state.category === category.id, function () {
        state.category = category.id;
        renderAll();
      }));
    });
  }

  /* ---------- 榜单 ---------- */

  function filteredBoard() {
    let rows = (DATA.boards && DATA.boards[state.region]) || [];
    if (state.category !== 'all') {
      rows = rows.filter(function (row) { return metaOf(row.t).category === state.category; });
    }
    if (state.query) {
      const query = state.query.toLowerCase();
      rows = rows.filter(function (row) {
        const meta = metaOf(row.t);
        return row.t.toLowerCase().indexOf(query) >= 0 ||
          String(meta.cn || '').toLowerCase().indexOf(query) >= 0;
      });
    }
    return rows;
  }

  function renderBoard() {
    const body = WS.$('board-body');
    const rows = filteredBoard().slice(0, TOP_N);
    body.innerHTML = '';

    rows.forEach(function (row, index) {
      const meta = metaOf(row.t);
      const detailUrl = 'detail.html?term=' + encodeURIComponent(row.t);
      const termCell = WS.el('td', { class: 'term-cell', html:
        '<a class="term-link" href="' + detailUrl + '">' + WS.escapeHtml(row.t) + '</a>' +
        (meta.cn ? '<span class="term-cn">' + WS.escapeHtml(meta.cn) + '</span>' : '') +
        '<span class="tag term-cat">' + WS.escapeHtml(categoryLabel(meta.category)) + '</span>' });

      body.append(WS.el('tr', { class: index < 3 ? 'row-top' : '' }, [
        WS.el('td', { class: 'rank-cell', text: String(index + 1) }),
        termCell,
        WS.el('td', { html:
          '<div class="heat-cell"><div class="heat-bar"><i style="width:' + row.v + '%"></i></div>' +
          '<span class="heat-value">' + row.v + '</span></div>' }),
        WS.el('td', { html: WS.deltaHtml(row) }),
        WS.el('td', { html: WS.sparkline(row.s || []) }),
      ]));
    });

    if (!rows.length) {
      body.append(WS.el('tr', {}, [WS.el('td', {
        colspan: 5, class: 'empty-state', text: '没有匹配的关键词，试试换个分类或清空搜索。',
      })]));
    }

    WS.$('result-count').textContent = rows.length + ' 个关键词';
    WS.$('board-sub').textContent = (regionLabel(state.region) + ' · ' +
      categoryLabel(state.category) + ' · 窗口 ' + (DATA.meta.window || 'realtime'));
  }

  function regionLabel(id) {
    const found = (DATA.regions || []).filter(function (region) { return region.id === id; })[0];
    return found ? found.label : id;
  }

  /* ---------- 飙升榜 ---------- */

  function renderBreakout() {
    const box = WS.$('breakout-list');
    let items = (DATA.breakout && DATA.breakout[state.region]) || [];
    if (state.category !== 'all') {
      items = items.filter(function (item) { return item.category === state.category; });
    }
    items = items.slice(0, 10);
    box.innerHTML = '';

    if (!items.length) {
      box.append(WS.el('p', { class: 'breakout-empty', text: '本期该筛选下暂无飙升关键词。' }));
      return;
    }

    items.forEach(function (item, index) {
      const meta = metaOf(item.term);
      box.append(WS.el('div', { class: 'breakout-item' }, [
        WS.el('span', { class: 'breakout-rank', text: String(index + 1) }),
        WS.el('div', { class: 'breakout-main' }, [
          WS.el('a', {
            class: 'breakout-term', href: 'detail.html?term=' + encodeURIComponent(item.term),
            text: item.term, style: 'display:block;color:inherit;text-decoration:none',
          }),
          WS.el('span', { class: 'breakout-meta', text:
            categoryLabel(meta.category) + ' · 当前热度 ' + item.current +
            (item.head_growth !== null && item.head_growth !== undefined ? ' · 首尾 ' + (item.head_growth > 0 ? '+' : '') + item.head_growth + '%' : '') }),
        ]),
        WS.el('span', { class: 'breakout-growth', html: '+' + item.growth + '<small>%</small>' }),
      ]));
    });
  }

  function renderSummary() {
    WS.$('summary-text').textContent = DATA.summary || '本期暂无摘要。';
  }

  function renderAll() {
    renderRegionChips();
    renderCategoryChips();
    renderBoard();
    renderBreakout();
  }

  function bindInputs() {
    WS.$('search').addEventListener('input', function (event) {
      state.query = event.target.value.trim();
      renderBoard();
    });
    WS.$('reset').addEventListener('click', function () {
      state.region = 'world';
      state.category = 'all';
      state.query = '';
      WS.$('search').value = '';
      renderAll();
    });
  }

  async function boot() {
    WS.initPage();
    try {
      DATA = await WS.loadData('trending', 'WS_TRENDING');
    } catch (error) {
      WS.$('board-body').innerHTML =
        '<tr><td colspan="5" class="empty-state">数据还没生成。请先运行采集：<code>python -m collector.main</code></td></tr>';
      return;
    }
    (DATA.categories || []).forEach(function (category) { CATEGORY_LABEL[category.id] = category.label; });
    WS.renderMeta(DATA.meta || {});
    renderSummary();
    renderAll();
    bindInputs();
  }

  boot();
})();
