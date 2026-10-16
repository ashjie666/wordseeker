/* ==========================================================================
   WordSeeker · 游戏频道
   数据：web/data/games.json（file:// 下回退到 data/games.js 的 window.WS_GAMES）
   ========================================================================== */

'use strict';

(function () {
  const state = { type: 'all', region: 'us', window: 'realtime', compare: [] };
  let DATA = null;
  const MAX_COMPARE = 5;
  const MIN_COMPARE = 2;

  function chip(label, active, onClick) {
    return WS.el('button', {
      class: 'chip', type: 'button',
      'aria-pressed': active ? 'true' : 'false',
      onclick: onClick, text: label,
    });
  }

  function thinSeries(series, target) {
    if (!series || series.length <= target) return series || [];
    const step = (series.length - 1) / (target - 1);
    const out = [];
    for (let index = 0; index < target; index += 1) out.push(series[Math.round(index * step)]);
    return out;
  }

  /* ---------- 取数 ---------- */

  function seriesOf(term) {
    return ((DATA.compare || {})[term] || {})[state.window] || [];
  }

  function gameList() {
    let games = DATA.games || [];
    if (state.type !== 'all') {
      games = games.filter(function (game) { return game.game_type === state.type; });
    }
    return games.map(function (game) {
      const series = seriesOf(game.term);
      const base = (game.heat || {})[state.region] || {};
      let value = base.v || 0;
      if (series.length) value = series[series.length - 1][1];
      return {
        term: game.term, cn: game.cn, studio: game.studio, game_type: game.game_type,
        value: value, delta: (base.d === undefined ? null : base.d),
        percent: (base.p === undefined ? null : base.p),
        series: series,
      };
    }).sort(function (a, b) { return b.value - a.value || a.term.localeCompare(b.term); });
  }

  function regionLabel(id) {
    const found = (DATA.regions || []).filter(function (region) { return region.id === id; })[0];
    return found ? found.label : id;
  }

  function categoryOfType(id) {
    const found = (DATA.game_types || []).filter(function (type) { return type.id === id; })[0];
    return found ? found.label : id;
  }

  /* ---------- 筛选器 ---------- */

  function renderFilters() {
    const typeBox = WS.$('filter-type');
    typeBox.innerHTML = '';
    (DATA.game_types || []).forEach(function (type) {
      typeBox.append(chip(type.label, state.type === type.id, function () {
        state.type = type.id;
        renderAll();
      }));
    });

    const regionBox = WS.$('filter-region');
    regionBox.innerHTML = '';
    (DATA.regions || []).filter(function (region) { return region.group !== 'global'; })
      .forEach(function (region) {
        regionBox.append(chip(region.group_label || region.label, state.region === region.id, function () {
          state.region = region.id;
          renderAll();
        }));
      });

    const windowBox = WS.$('filter-window');
    windowBox.innerHTML = '';
    (DATA.compare_windows || []).forEach(function (item) {
      windowBox.append(chip(item.label, state.window === item.id, function () {
        state.window = item.id;
        renderAll();
      }));
    });
  }

  /* ---------- 卡片 ---------- */

  function renderCards() {
    const grid = WS.$('game-grid');
    const games = gameList();
    grid.innerHTML = '';

    games.forEach(function (game) {
      const picked = state.compare.indexOf(game.term) >= 0;
      const detailUrl = 'detail.html?term=' + encodeURIComponent(game.term);
      const card = WS.el('div', { class: 'game-card' }, [
        WS.el('div', { class: 'game-card-head' }, [
          WS.el('a', { class: 'game-card-title', href: detailUrl, text: game.term,
            style: 'color:inherit;text-decoration:none' }),
          WS.el('span', { class: 'game-card-sub', text: (game.cn || '') + (game.studio ? ' · ' + game.studio : '') }),
        ]),
        WS.el('div', { class: 'heat-cell' }, [
          WS.el('div', { class: 'heat-bar', html: '<i style="width:' + game.value + '%"></i>' }),
          WS.el('span', { class: 'heat-value', text: String(game.value) }),
        ]),
        WS.el('div', { class: 'game-card-foot' }, [
          WS.el('span', { html: WS.deltaHtml({ d: game.delta, p: game.percent }) }),
          WS.el('span', { class: 'tag', text: categoryOfType(game.game_type) }),
          WS.el('span', { class: 'spark-wrap', html: WS.sparkline(thinSeries(game.series, 12).map(function (point) { return point[1]; })) }),
        ]),
        WS.el('div', { class: 'game-card-foot' }, [
          chip(picked ? '已加入对比' : '加入对比', picked, function () { toggleCompare(game.term); }),
          WS.el('a', { class: 'text-btn', href: detailUrl, text: '查看详情 →',
            style: 'text-decoration:none;display:inline-block' }),
        ]),
      ]);
      grid.append(card);
    });

    if (!games.length) {
      grid.append(WS.el('p', { class: 'breakout-empty', text: '该游戏类型下暂无关键词。' }));
    }

    WS.$('result-count').textContent = games.length + ' 款游戏';
    WS.$('games-sub').textContent = regionLabel(state.region) + ' · ' + categoryOfType(state.type);
  }

  /* ---------- 对比 ---------- */

  function toggleCompare(term) {
    const index = state.compare.indexOf(term);
    if (index >= 0) state.compare.splice(index, 1);
    else if (state.compare.length < MAX_COMPARE) state.compare.push(term);
    renderPicker();
    renderChart();
    renderCards();
  }

  function renderPicker() {
    const box = WS.$('compare-picker');
    box.innerHTML = '';
    (DATA.games || []).forEach(function (game) {
      const picked = state.compare.indexOf(game.term) >= 0;
      box.append(chip(game.term, picked, function () { toggleCompare(game.term); }));
    });
    WS.$('compare-sub').textContent = '已选 ' + state.compare.length + ' / ' + MAX_COMPARE +
      ' 款（至少 ' + MIN_COMPARE + ' 款）· 窗口 ' + state.window;
  }

  function renderChart() {
    const host = WS.$('compare-chart');
    const legend = WS.$('compare-legend');
    legend.innerHTML = '';

    if (state.compare.length < MIN_COMPARE) {
      host.innerHTML = '<p class="metric-note">请至少选择 ' + MIN_COMPARE + ' 款游戏进行对比（最多 ' + MAX_COMPARE + ' 款）。</p>';
      return;
    }

    const seriesList = state.compare.map(function (term, index) {
      return { name: term, color: WS.palette[index % WS.palette.length], points: seriesOf(term) };
    });
    host.innerHTML = WS.lineChart(seriesList, {});

    seriesList.forEach(function (item) {
      const last = item.points.length ? item.points[item.points.length - 1][1] : '—';
      legend.append(WS.el('span', { class: 'legend-item', html:
        '<span class="legend-dot" style="background:' + item.color + '"></span>' +
        WS.escapeHtml(item.name) + ' <strong>' + last + '</strong>' }));
    });
  }

  /* ---------- 飙升榜 ---------- */

  function renderBreakout() {
    const box = WS.$('breakout-list');
    const items = ((DATA.breakout || {})[state.region] || []).slice(0, 10);
    box.innerHTML = '';

    if (!items.length) {
      box.append(WS.el('p', { class: 'breakout-empty', text: '本期该地区暂无游戏飙升词。' }));
      return;
    }

    items.forEach(function (item, index) {
      box.append(WS.el('div', { class: 'breakout-item' }, [
        WS.el('span', { class: 'breakout-rank', text: String(index + 1) }),
        WS.el('div', { class: 'breakout-main' }, [
          WS.el('a', { class: 'breakout-term', text: item.term,
            href: 'detail.html?term=' + encodeURIComponent(item.term),
            style: 'display:block;color:inherit;text-decoration:none' }),
          WS.el('span', { class: 'breakout-meta', text: (item.cn || '') + ' · 当前热度 ' + item.current }),
        ]),
        WS.el('span', { class: 'breakout-growth', html: '+' + item.growth + '<small>%</small>' }),
      ]));
    });
  }

  function renderAll() {
    renderFilters();
    renderCards();
    renderPicker();
    renderChart();
    renderBreakout();
  }

  async function boot() {
    WS.initPage();
    try {
      DATA = await WS.loadData('games', 'WS_GAMES');
    } catch (error) {
      WS.$('game-grid').innerHTML = '<p class="breakout-empty">数据还没生成。请先运行采集：<code>python -m collector.main</code></p>';
      return;
    }
    WS.renderMeta(DATA.meta || {});

    const firstRegion = (DATA.regions || []).filter(function (region) { return region.group !== 'global'; })[0];
    if (firstRegion) state.region = firstRegion.id;

    const initialWindow = (DATA.compare_windows || [])[0];
    if (initialWindow) state.window = initialWindow.id;

    state.compare = gameList().slice(0, MIN_COMPARE).map(function (game) { return game.term; });
    renderAll();
  }

  boot();
})();
