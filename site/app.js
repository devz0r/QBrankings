(() => {
  'use strict';

  const TEAM = {
    ARI: ['#97233F', '#fff'], ATL: ['#A71930', '#fff'], BAL: ['#241773', '#fff'], BUF: ['#00338D', '#fff'],
    CAR: ['#0085CA', '#fff'], CHI: ['#0B162A', '#fff'], CIN: ['#FB4F14', '#fff'], CLE: ['#311D00', '#fff'],
    DAL: ['#003594', '#fff'], DEN: ['#FB4F14', '#002244'], DET: ['#0076B6', '#fff'], GB: ['#203731', '#FFB612'],
    HOU: ['#03202F', '#fff'], IND: ['#002C5F', '#fff'], JAX: ['#006778', '#fff'], KC: ['#E31837', '#fff'],
    LA: ['#003594', '#FFD100'], LAC: ['#0080C6', '#fff'], LV: ['#000000', '#A5ACAF'], MIA: ['#008E97', '#fff'],
    MIN: ['#4F2683', '#FFC62F'], NE: ['#002244', '#fff'], NO: ['#D3BC8D', '#101820'], NYG: ['#0B2265', '#fff'],
    NYJ: ['#125740', '#fff'], PHI: ['#004C54', '#fff'], PIT: ['#101820', '#FFB612'], SEA: ['#002244', '#69BE28'],
    SF: ['#AA0000', '#fff'], TB: ['#D50A0A', '#fff'], TEN: ['#4B92DB', '#0C2340'], WAS: ['#5A1414', '#FFB612'],
    OAK: ['#000000', '#A5ACAF'], SD: ['#0080C6', '#FFC20E'], STL: ['#002244', '#B3995D'],
  };
  const TIERS = [[90, 'MVP level'], [80, 'Elite'], [70, 'Very good'], [58, 'Above average'], [42, 'Average'],
    [30, 'Below average'], [20, 'Poor'], [-1, 'Struggling']];
  const SVG = 'http://www.w3.org/2000/svg';
  // Why the historical exceptions in the clear-cut-pair check come out the way they do.
  const WHY = {
    '2020|Joe Burrow|Mitchell Trubisky': "Trubisky's games came against some of the softest defenses in the league",
    '2021|Jimmy Garoppolo|Kirk Cousins': 'the box scores were nearly tied, and Garoppolo gained 8.7 yards per attempt to Cousins\' 7.6',
  };

  const state = {
    index: null, season: null, data: null, validation: null,
    sort: { key: 'cqr', dir: -1 }, query: '', showAll: false, open: new Set(), mode: 'season', view: 'list',
  };

  // ---------- helpers ----------
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'style') n.setAttribute('style', v);
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return n;
  }
  function svg(tag, attrs, ...kids) {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) n.setAttribute(k, v);
    for (const kid of kids.flat()) if (kid != null) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return n;
  }
  const fmt1 = (v) => (v == null ? '–' : v.toFixed(1));
  const signed = (v, d = 1) => (v == null ? '–' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d));
  const tierOf = (s) => TIERS.find(([t]) => s >= t)[1];
  const ordinal = (n) => n + (['th', 'st', 'nd', 'rd'][(n % 100 - 20) % 10] || ['th', 'st', 'nd', 'rd'][n % 100] || 'th');
  function store(k, v) { try { localStorage.setItem('cqr:' + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } }
  function recall(k, d) { try { const v = localStorage.getItem('cqr:' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }
  function teamChip(t) {
    const [bg, fg] = TEAM[t] || ['#55605a', '#fff'];
    return el('span', { class: 'team-chip', style: `background:${bg};color:${fg}`, text: t });
  }
  function dateText(iso) {
    const d = new Date(iso.length <= 10 ? iso + 'T12:00:00' : iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  async function getJSON(path) {
    const embedded = window.CQR_DATA;
    if (embedded) {
      if (path === 'index') return embedded.index;
      if (path === 'validation') return embedded.validation;
      if (path === 'holdout') return embedded.holdout;
      return embedded.seasons[path];
    }
    const res = await fetch(`data/${path}.json`, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`Couldn't load data/${path}.json (${res.status})`);
    return res.json();
  }

  // ---------- mode: this season's CQR, or the best-QB (talent) estimate ----------
  const talentMode = () => state.mode === 'talent';
  const score = (q) => (talentMode() ? q.talent.cqr : q.cqr);
  const rankOf = (q) => (talentMode() ? q.talent.rank : q.rank);
  const isRanked = (q) => (talentMode() ? q.talent.rank != null : q.qualified);

  // ---------- columns ----------
  const box = (k) => (q) => q.box[k];
  const COLS = [
    { key: 'rank', label: 'Rk', cls: 'rk', get: (q) => rankOf(q) ?? 999, cell: (q) => (rankOf(q) ?? '–'), title: 'Rank' },
    { key: 'move', label: '±', cls: 'mv', sortable: false, cell: moveCell, title: 'Change since last week' },
    { key: 'name', label: 'Quarterback', cls: 'qb', get: (q) => q.name, cell: qbCell },
    { key: 'cqr', label: () => (talentMode() ? 'Rating' : 'CQR'), cls: 'score', get: score, cell: (q) => fmt1(score(q)) },
    { key: 'bar', label: 'vs. average', cls: 'bar-cell left', sortable: false, cell: barCell },
    { key: 'trend', label: () => (talentMode() ? 'Based on' : 'Trend'), cls: 'spark', sortable: false, cell: sparkCell, title: 'Season-to-date CQR week by week, or what the best-QB rating is based on' },
    { key: 'ppg', label: 'Total', cls: 'num col-comp sep', get: (q) => q.pts_per_game, cell: (q) => signed(q.pts_per_game), title: 'Points per game added vs. an average QB' },
    { key: 'passing', label: 'Pass', cls: 'num col-comp', get: (q) => q.components.passing, cell: (q) => signed(q.components.passing) },
    { key: 'rushing', label: 'Rush', cls: 'num col-comp', get: (q) => q.components.rushing, cell: (q) => signed(q.components.rushing) },
    { key: 'sacks', label: 'Sacks', cls: 'num col-comp', get: (q) => q.components.sacks, cell: (q) => signed(q.components.sacks), title: 'Sacks and botched snaps' },
    { key: 'schedule', label: 'Sched', cls: 'num col-comp', get: (q) => q.components.schedule, cell: (q) => signed(q.components.schedule), title: 'Credit for tough defenses faced (negative = soft schedule)' },
    { key: 'games', label: 'G', cls: 'num col-box sep', get: (q) => q.games, cell: (q) => q.games },
    { key: 'att', label: 'Cmp-Att', cls: 'num col-box', get: box('att'), cell: (q) => `${q.box.cmp}-${q.box.att}`, title: 'Completions-attempts' },
    { key: 'pass_yds', label: 'Yds', cls: 'num col-box', get: box('pass_yds'), cell: (q) => q.box.pass_yds.toLocaleString() },
    { key: 'pass_td', label: 'TD', cls: 'num col-box', get: box('pass_td'), cell: (q) => q.box.pass_td },
    { key: 'ints', label: 'Int', cls: 'num col-box', get: box('ints'), cell: (q) => q.box.ints },
    { key: 'sacks_n', label: 'Sk', cls: 'num col-box', get: box('sacks'), cell: (q) => q.box.sacks },
    { key: 'rush_yds', label: 'Rush', cls: 'num col-box', get: box('rush_yds'), cell: (q) => q.box.rush_yds.toLocaleString(), title: 'Rushing yards (designed runs and scrambles)' },
    { key: 'rush_td', label: 'RTD', cls: 'num col-box', get: box('rush_td'), cell: (q) => q.box.rush_td, title: 'Rushing touchdowns' },
    { key: 'rating', label: 'Rate', cls: 'num col-box', get: box('rating'), cell: (q) => fmt1(q.box.rating), title: 'NFL passer rating' },
  ];

  function moveCell(q) {
    if (talentMode()) return el('span', { class: 'mv flat', text: q.rank ? `S${q.rank}` : '', title: q.rank ? `${ordinal(q.rank)} in this season's CQR` : '' });
    if (q.rank == null || q.prev_rank == null) return el('span', { class: 'mv flat', text: '' });
    const d = q.prev_rank - q.rank;
    if (d === 0) return el('span', { class: 'mv flat', text: '–', title: 'No change' });
    return el('span', { class: 'mv ' + (d > 0 ? 'up' : 'down'), text: (d > 0 ? '▲' : '▼') + Math.abs(d),
      title: `${d > 0 ? 'Up' : 'Down'} ${Math.abs(d)} from ${ordinal(q.prev_rank)}` });
  }
  function qbCell(q) {
    const teams = q.teams.length > 1 ? q.teams : [q.team];
    return [el('span', { class: 'qb-name', text: q.name }),
      el('span', { class: 'qb-meta' }, teams.map(teamChip), `${q.games} G · ${q.dropbacks} DB`)];
  }
  function barCell(q) {
    const v = Math.max(0, Math.min(100, score(q)));
    const good = v >= 50;
    const left = good ? 50 : v;
    const width = Math.abs(v - 50);
    return el('div', { class: 'bar', role: 'img', 'aria-label': `${fmt1(v)}, ${good ? 'above' : 'below'} league average` },
      el('span', { class: 'fill ' + (good ? 'good' : 'bad'), style: `left:${left}%;width:${width}%` }),
      el('span', { class: 'avg' }));
  }
  function basisCell(q) {
    const t = q.talent, seasonPct = Math.round(t.share_season * 100), histPct = Math.round(t.share_history * 100);
    return el('div', { class: 'basis', title: `${seasonPct}% this season, ${histPct}% past seasons, ${100 - seasonPct - histPct}% starting point` },
      el('span', { class: 'basis-bar' },
        el('i', { class: 'b-season', style: `width:${seasonPct}%` }), el('i', { class: 'b-hist', style: `width:${histPct}%` })),
      el('span', { class: 'basis-text', text: `${seasonPct}% this yr` }));
  }
  function sparkCell(q) {
    if (talentMode()) return basisCell(q);
    const h = q.history.filter((p) => p.cqr != null);
    if (h.length < 2) return '';
    const W = 88, H = 26, weeks = state.data.weeks, w0 = weeks[0], w1 = weeks[weeks.length - 1];
    const x = (w) => 3 + ((w - w0) / Math.max(1, w1 - w0)) * (W - 6);
    const y = (s) => 3 + (1 - s / 100) * (H - 6);
    const pts = h.map((p) => `${x(p.week).toFixed(1)},${y(p.cqr).toFixed(1)}`).join(' ');
    const last = h[h.length - 1];
    return svg('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true' },
      svg('line', { x1: 0, x2: W, y1: y(50), y2: y(50), stroke: 'var(--chalk)', 'stroke-width': 1.5 }),
      svg('polyline', { points: pts, fill: 'none', stroke: 'var(--muted)', 'stroke-width': 1.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }),
      svg('circle', { cx: x(last.week), cy: y(last.cqr), r: 3, fill: last.cqr >= 50 ? 'var(--good)' : 'var(--bad)', stroke: 'var(--surface)', 'stroke-width': 1.5 }));
  }

  // ---------- board ----------
  function renderHead() {
    const tr = document.getElementById('board-head');
    tr.replaceChildren(...COLS.map((c) => {
      const sortable = c.sortable !== false;
      const th = el('th', { class: c.cls, scope: 'col', title: c.title,
        'aria-sort': sortable && state.sort.key === c.key ? (state.sort.dir < 0 ? 'descending' : 'ascending') : null });
      const label = typeof c.label === 'function' ? c.label() : c.label;
      if (!sortable) { th.textContent = label; return th; }
      th.append(el('button', { type: 'button', text: label, onclick: () => {
        if (state.sort.key === c.key) state.sort.dir *= -1;
        else state.sort = { key: c.key, dir: ['name', 'rank'].includes(c.key) ? 1 : -1 };
        renderHead(); renderBoard();
      } }));
      return th;
    }));
  }

  function sorted(list) {
    const c = COLS.find((k) => k.key === state.sort.key) || COLS[3];
    return [...list].sort((a, b) => {
      const va = c.get(a), vb = c.get(b);
      if (typeof va === 'string') return va.localeCompare(vb) * state.sort.dir;
      return ((va ?? -1e9) - (vb ?? -1e9)) * state.sort.dir || (b.cqr - a.cqr);
    });
  }

  // Tiers are fixed score bands on the 0-100 scale (50 = league average), so a tier means the same
  // thing every week and every season, and a tier can be empty.
  const TIER_BANDS = [
    ['S', 85, 'MVP level', '#f24b26', '#fff'], ['A', 75, 'Elite', '#ffa62b', '#1b1b1b'],
    ['B', 62, 'Very good', '#ffcc2e', '#1b1b1b'], ['C', 50, 'Above average', '#17ad5c', '#fff'],
    ['D', 38, 'Below average', '#0d97ff', '#fff'], ['E', 25, 'Poor', '#9a4dff', '#fff'],
    ['F', -1, 'Struggling', '#ff47f0', '#1b1b1b'],
  ];

  function renderTiers() {
    const box = document.getElementById('tiers');
    const q = state.query.trim().toLowerCase();
    const list = state.data.qbs.filter((x) => (state.showAll || isRanked(x))
      && (!q || x.name.toLowerCase().includes(q) || x.teams.some((t) => t.toLowerCase() === q)))
      .sort((a, b) => score(b) - score(a));
    const label = talentMode() ? 'Best-QB rating' : 'CQR';
    box.replaceChildren(...TIER_BANDS.map(([t, min, name, bg, fg], i) => {
      const max = i ? TIER_BANDS[i - 1][1] : 100;
      const members = list.filter((x) => score(x) >= min && score(x) < (i ? max : 101));
      return el('div', { class: 'tier-row' },
        el('div', { class: 'tier-label', style: `background:${bg};color:${fg}` },
          el('span', { class: 'tier-letter', text: t }),
          el('span', { class: 'tier-range', text: i === 0 ? `${min}+` : min < 0 ? `under ${max}` : `${min}-${max}` })),
        el('div', { class: 'tier-cells', 'aria-label': `${t} tier, ${name}` },
          members.length ? members.map((x) => el('button', { type: 'button', class: 'tier-qb' + (isRanked(x) ? '' : ' unq'),
            title: `${x.name}: ${label} ${fmt1(score(x))}${rankOf(x) ? `, ${ordinal(rankOf(x))}` : ''}. Open in rankings`,
            onclick: () => { state.view = 'list'; syncViews(); state.open.add(x.id); renderView();
              requestAnimationFrame(() => document.querySelector('#board-body tr[aria-expanded="true"]')?.scrollIntoView({ block: 'center' })); } },
            teamChip(x.team), el('span', { class: 'tier-name', text: x.name }), el('span', { class: 'tier-score', text: fmt1(score(x)) })))
            : el('span', { class: 'tier-empty', text: `Nobody at ${name.toLowerCase()} level right now` })));
    }));
  }

  function syncViews() {
    document.querySelectorAll('.views button').forEach((btn) => btn.setAttribute('aria-pressed', String(btn.dataset.view === state.view)));
    document.getElementById('tiers').hidden = state.view !== 'tiers';
    document.getElementById('board-card').hidden = state.view === 'tiers';
  }

  function renderView() {
    if (state.view === 'tiers') renderTiers(); else renderBoard();
  }

  function renderBoard() {
    const body = document.getElementById('board-body');
    const q = state.query.trim().toLowerCase();
    const match = (x) => !q || x.name.toLowerCase().includes(q) || x.teams.some((t) => t.toLowerCase() === q) || x.team.toLowerCase().startsWith(q);
    const all = state.data.qbs.filter(match);
    const qual = sorted(all.filter(isRanked));
    const part = sorted(all.filter((x) => !isRanked(x)));
    const rows = [];
    const add = (x) => {
      const open = state.open.has(x.id);
      const tr = el('tr', { class: 'row' + (isRanked(x) ? '' : ' unq'), tabindex: 0, 'aria-expanded': open ? 'true' : 'false',
        onclick: () => toggle(x.id), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(x.id); } } },
      COLS.map((c) => el('td', { class: c.cls }, c.cell(x))));
      rows.push(tr);
      if (open) rows.push(detailRow(x));
    };
    qual.forEach(add);
    if (state.showAll && part.length) {
      rows.push(el('tr', { class: 'section-row' }, el('td', { colspan: COLS.length,
        text: talentMode() ? 'Not enough evidence yet (this season plus the last three)' : `Part-time QBs: fewer than ${state.data.qualify_dropbacks_per_team_game} dropbacks per team game` })));
      part.forEach(add);
    }
    if (!rows.length) rows.push(el('tr', {}, el('td', { class: 'empty', colspan: COLS.length, text: 'No quarterbacks match that search.' })));
    syncDetailWidth();
    body.replaceChildren(...rows);
  }

  function toggle(id) {
    if (state.open.has(id)) state.open.delete(id); else state.open.add(id);
    renderBoard();
  }

  // ---------- detail ----------
  function detailRow(q) {
    const td = el('td', { colspan: COLS.length });
    const grid = el('div', { class: 'detail-grid' },
      el('div', { class: 'detail-col' }, summaryPanel(q), componentsPanel(q)),
      el('div', { class: 'detail-col' }, weeklyPanel(q), logPanel(q)));
    td.append(grid);
    return el('tr', { class: 'detail' }, td);
  }

  // The detail panel stays the width of the visible table area, even when the table scrolls sideways.
  function syncDetailWidth() {
    const scroller = document.querySelector('.table-scroll');
    if (scroller) document.documentElement.style.setProperty('--detail-width', scroller.clientWidth + 'px');
  }

  function summaryPanel(q) {
    const nQual = state.data.qbs.filter((x) => x.qualified).length;
    const c = q.components;
    const parts = [];
    const ppg = q.pts_per_game;
    parts.push(ppg >= 0
      ? `${q.name} is adding ${signed(ppg)} points per game compared with an average quarterback`
      : `${q.name} is ${Math.abs(ppg).toFixed(1)} points per game worse than an average quarterback`);
    parts[0] += c.rushing >= 1.5 ? `, ${signed(c.rushing)} of it as a runner.` : '.';
    if (c.sacks <= -5) parts.push(`Sacks and botched snaps cost ${Math.abs(c.sacks).toFixed(1)} points a game.`);
    if (Math.abs(c.schedule) >= 0.5) parts.push(c.schedule > 0
      ? `The defenses faced have been tougher than most, worth ${signed(c.schedule)} a game in the adjustment.`
      : `The defenses faced have been softer than most, so the adjustment takes away ${Math.abs(c.schedule).toFixed(1)} a game.`);
    const b = q.box;
    return el('div', { class: 'panel' },
      el('h3', { text: q.qualified ? `${ordinal(q.rank)} of ${nQual} qualified` : 'Part-time QB' }),
      el('div', { class: 'big', text: fmt1(q.cqr) }),
      el('div', { class: 'big-sub', text: `${tierOf(q.cqr)} · ${q.per_dropback >= 0 ? '+' : '−'}${Math.abs(q.per_dropback).toFixed(3)} points per dropback` }),
      el('p', { class: 'summary', text: parts.join(' ') }),
      el('p', { class: 'summary talent-line' }, el('strong', { text: `Best-QB rating ${fmt1(q.talent.cqr)}` }),
        q.talent.rank ? ` (${ordinal(q.talent.rank)})` : '',
        `: ${Math.round(q.talent.share_season * 100)}% this season, ${Math.round(q.talent.share_history * 100)}% past seasons, ` +
        `${100 - Math.round(q.talent.share_season * 100) - Math.round(q.talent.share_history * 100)}% starting point.`),
      el('dl', { class: 'facts' },
        el('dt', { text: 'Completion %' }), el('dd', { text: b.cmp_pct == null ? '–' : `${fmt1(b.cmp_pct)}%` }),
        el('dt', { text: 'Yards per attempt' }), el('dd', { text: b.ypa == null ? '–' : b.ypa.toFixed(1) }),
        el('dt', { text: 'ANY/A' }), el('dd', { text: b.anya == null ? '–' : b.anya.toFixed(2) }),
        el('dt', { text: 'CPOE' }), el('dd', { text: b.cpoe == null ? '–' : `${signed(b.cpoe)}%` }),
        el('dt', { text: 'Fumbles (lost)' }), el('dd', { text: `${b.fumbles} (${b.fumbles_lost})` }),
        el('dt', { text: 'Sack yards' }), el('dd', { text: b.sack_yds })));
  }

  function componentsPanel(q) {
    const items = [['Passing', q.components.passing], ['Rushing', q.components.rushing],
      ['Sacks & bad snaps', q.components.sacks], ['Schedule', q.components.schedule]];
    const M = state.compMax;
    const rows = items.map(([label, v]) => {
      const w = (Math.min(Math.abs(v), M) / M) * 50;
      return el('div', { class: 'comp-row', role: 'listitem', 'aria-label': `${label} ${signed(v)} points per game` },
        el('span', { class: 'comp-label', text: label }),
        el('span', { class: 'comp-track' },
          el('span', { class: 'comp-fill ' + (v >= 0 ? 'good' : 'bad'), style: v >= 0 ? `left:50%;width:${w}%` : `right:50%;width:${w}%` }),
          el('span', { class: 'comp-zero' })),
        el('span', { class: 'comp-val', text: signed(v) }));
    });
    return el('div', { class: 'panel' },
      el('h3', { text: 'Where the value comes from' }),
      el('div', { class: 'comps', role: 'list' }, rows),
      el('p', { class: 'summary', text: `Points per game versus an average QB on the same snaps. Total: ${signed(q.pts_per_game)}.` }));
  }

  function weeklyPanel(q) {
    const wrap = el('div', { class: 'chart', tabindex: 0, role: 'img',
      'aria-label': `${q.name}: season-to-date CQR by week and single-game scores. Use the arrow keys to read each week.` });
    const panel = el('div', { class: 'panel' }, el('h3', { text: 'Week by week' }),
      el('div', { class: 'legend' },
        el('span', {}, el('i', { class: 'lk-line' }), 'Season-to-date CQR'),
        el('span', {}, el('i', { class: 'lk-dot' }), 'Single-game score'),
        el('span', {}, el('i', { class: 'lk-avg' }), 'League average')), wrap);
    const tip = el('div', { class: 'tip', hidden: true });
    let chart = null, lastWidth = 0;
    const draw = () => {
      const width = Math.round(wrap.clientWidth);
      if (!width || width === lastWidth) return;
      lastWidth = width;
      chart = drawWeekly(q, width, tip);
      wrap.replaceChildren(chart.node, tip);
    };
    requestAnimationFrame(draw);
    if (window.ResizeObserver) new ResizeObserver(draw).observe(wrap);
    wrap.addEventListener('keydown', (e) => {
      if (!chart || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
      e.preventDefault();
      chart.step(e.key === 'ArrowRight' ? 1 : -1);
    });
    wrap.addEventListener('blur', () => chart && chart.hide());
    wrap.addEventListener('click', (e) => e.stopPropagation());
    return panel;
  }

  // Line (season-to-date) + dots (single games) on one 0-100 axis, drawn at the real pixel width.
  function drawWeekly(q, W, tip) {
    const H = 220, m = { l: 30, r: 14, t: 10, b: 28 };
    const weeks = state.data.weeks;
    const w0 = weeks[0], w1 = Math.max(weeks[weeks.length - 1], w0 + 1);
    const x = (w) => m.l + ((w - w0) / (w1 - w0)) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - v / 100) * (H - m.t - m.b);
    const s = svg('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` });
    for (const t of [0, 25, 75, 100]) {
      s.append(svg('line', { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: 'var(--line)', 'stroke-width': 1 }));
    }
    for (const t of [0, 25, 50, 75, 100]) {
      s.append(svg('text', { x: m.l - 6, y: y(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--muted)' }, String(t)));
    }
    s.append(svg('line', { x1: m.l, x2: W - m.r, y1: y(50), y2: y(50), stroke: 'var(--chalk)', 'stroke-width': 2.5 }));
    const every = Math.max(1, Math.ceil(weeks.length / Math.max(2, Math.floor((W - m.l - m.r) / 34))));
    weeks.forEach((w, i) => {
      if (i % every && i !== weeks.length - 1) return;
      s.append(svg('text', { x: x(w), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--muted)' }, `W${w}`));
    });
    for (const g of q.games_log.filter((k) => k.cqr != null && k.dropbacks >= 5)) {
      s.append(svg('circle', { cx: x(g.week), cy: y(g.cqr), r: 4.5, fill: 'var(--dot)', stroke: 'var(--surface)', 'stroke-width': 2 }));
    }
    const hist = q.history.filter((p) => p.cqr != null);
    if (hist.length) {
      s.append(svg('polyline', { points: hist.map((p) => `${x(p.week)},${y(p.cqr)}`).join(' '), fill: 'none',
        stroke: 'var(--ink)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
      const last = hist[hist.length - 1];
      s.append(svg('circle', { cx: x(last.week), cy: y(last.cqr), r: 4.5, fill: 'var(--ink)', stroke: 'var(--surface)', 'stroke-width': 2 }));
      s.append(svg('text', { x: x(last.week) - 8, y: y(last.cqr) + (last.cqr > 85 ? 18 : -10), 'text-anchor': 'end',
        'font-size': 12, 'font-weight': 700, fill: 'var(--ink)' }, fmt1(last.cqr)));
    }
    const cross = svg('line', { y1: m.t, y2: H - m.b, stroke: 'var(--line-strong)', 'stroke-width': 1, visibility: 'hidden' });
    const hit = svg('rect', { x: m.l - 10, y: 0, width: W - m.l - m.r + 20, height: H, fill: 'transparent' });
    s.append(cross, hit);
    let cur = null;
    const show = (w) => {
      cur = w;
      const g = q.games_log.find((k) => k.week === w);
      const h = q.history.find((k) => k.week === w);
      cross.setAttribute('x1', x(w)); cross.setAttribute('x2', x(w)); cross.setAttribute('visibility', 'visible');
      const lines = [el('div', {}, el('strong', { text: `Week ${w}` }), g ? ` · ${g.home ? 'vs' : '@'} ${g.opp}, ${g.result}` : ' · did not play')];
      if (g && g.cqr != null) lines.push(el('div', {}, el('span', { class: 'tk', style: 'background:var(--dot)' }),
        `Game ${fmt1(g.cqr)} · ${g.cmp}/${g.att}, ${g.pass_yds} yds, ${g.pass_td} TD, ${g.ints} INT`));
      if (h && h.cqr != null) lines.push(el('div', {}, el('span', { class: 'tk', style: 'background:var(--bg)' }),
        `Season ${fmt1(h.cqr)}${h.rank ? ` · ${ordinal(h.rank)}` : ''}`));
      tip.replaceChildren(...lines);
      tip.hidden = false;
      tip.style.left = Math.max(110, Math.min(W - 110, x(w))) + 'px';
      tip.style.top = '4px';
    };
    const hide = () => { cur = null; cross.setAttribute('visibility', 'hidden'); tip.hidden = true; };
    hit.addEventListener('pointermove', (e) => {
      const r = s.getBoundingClientRect();
      const vx = ((e.clientX - r.left) / r.width) * W;
      show(weeks.reduce((best, w) => (Math.abs(x(w) - vx) < Math.abs(x(best) - vx) ? w : best), weeks[0]));
    });
    hit.addEventListener('pointerleave', hide);
    const step = (d) => {
      const i = cur == null ? weeks.length - 1 : weeks.indexOf(cur) + d;
      show(weeks[Math.max(0, Math.min(weeks.length - 1, i))]);
    };
    return { node: s, show, hide, step };
  }

  function logPanel(q) {
    const head = ['Wk', 'Opp', 'Result', 'Game', 'Cmp-Att', 'Yds', 'TD', 'Int', 'Sk', 'Rush', 'Rate'];
    const rows = q.games_log.map((g) => el('tr', {},
      el('td', { class: 'left', text: g.week }),
      el('td', { class: 'left' }, `${g.home ? 'vs' : '@'} `, teamChip(g.opp)),
      el('td', { class: 'left', text: g.result }),
      el('td', {}, el('span', { class: 'chip-score ' + (g.cqr >= 50 ? 'good' : 'bad'), text: fmt1(g.cqr) })),
      el('td', { text: `${g.cmp}-${g.att}` }), el('td', { text: g.pass_yds }), el('td', { text: g.pass_td }),
      el('td', { text: g.ints }), el('td', { text: g.sacks }), el('td', { text: `${g.rush_att}-${g.rush_yds}` }),
      el('td', { text: fmt1(g.rating) })));
    return el('div', { class: 'panel log' }, el('h3', { text: 'Game log' }),
      el('p', { class: 'summary', text: 'Game scores use the same formula on one game, with a 10-dropback cushion.' }),
      el('div', { class: 'gamelog-wrap' }, el('table', { class: 'gamelog' },
        el('thead', {}, el('tr', {}, head.map((h, i) => el('th', { class: i < 3 ? 'left' : null, text: h })))),
        el('tbody', {}, rows))));
  }

  // ---------- page ----------
  function renderSeason() {
    const d = state.data;
    const qual = d.qbs.filter((x) => x.qualified).sort((a, b) => a.rank - b.rank);
    const isCurrent = d.season === state.index.current;
    const done = !isCurrent || d.through_week >= 18;
    document.getElementById('season-label').textContent =
      `${d.season} regular season · ${done && d.through_week >= 17 ? 'final' : `through Week ${d.through_week}`}`;
    if (talentMode()) {
      const tq = d.qbs.filter((x) => x.talent.rank != null).sort((p, r) => p.talent.rank - r.talent.rank);
      const [ta, tb, tc] = tq;
      document.getElementById('lede').textContent = ta ? `${ta.name} ${done && d.through_week >= 17 ? 'finished as' : 'is'} the best quarterback ${done && d.through_week >= 17 ? `of ${d.season}` : 'right now'}` : 'Best quarterbacks';
      document.getElementById('lede-sub').textContent = (tb && tc ? `${tb.name} and ${tc.name} are next. ` : '') +
        "This power ranking leans on this season's CQR and steadies it with last season. Last season's weight fades as the year goes on and is gone by about Week 17.";
      document.getElementById('board-note').textContent =
        "Best-QB rating = (this season's value × dropbacks + h × last season's value × dropbacks + 50 dropbacks at a starting point) ÷ total weight, on the same 0-100 curve as CQR. " +
        "h starts at 0.2 and fades to zero by 600 dropbacks this season, so about five games in this season is roughly 60% of the rating. QBs in their 2nd-4th seasons get +0.06 on last season's value, because young QBs tend to improve. " +
        'Tested on 2022-2025 (not used for fitting), it predicts the rest of a season about as well as a version weighted toward three past seasons, and better from midseason on. ' +
        "Ranked: QBs with at least 150 dropbacks this season and last. S-numbers show this season's CQR rank.";
      state.compMax = Math.max(4, ...qual.flatMap((x) => Object.values(x.components).map(Math.abs)));
      document.getElementById('updated').textContent =
        `Data through ${dateText(d.last_game_date)} (${d.games_played} games). Rebuilt ${dateText(d.generated_at)}.`;
      renderHead();
      renderView();
      return;
    }
    const [a, b, c] = qual;
    document.getElementById('lede').textContent = a ? `${a.name} ${done && d.through_week >= 17 ? 'led' : 'leads'} the NFL in CQR` : 'Quarterback rankings';
    let sub = b && c ? `${b.name} and ${c.name} round out the top three` : '';
    if (isCurrent && !done) {
      const movers = qual.filter((x) => x.prev_rank != null).map((x) => ({ x, d: x.prev_rank - x.rank })).sort((p, q) => q.d - p.d);
      if (movers.length && movers[0].d >= 3) sub += `. Biggest climb this week: ${movers[0].x.name} (${ordinal(movers[0].x.prev_rank)} to ${ordinal(movers[0].x.rank)})`;
    }
    document.getElementById('lede-sub').textContent = (sub ? sub + '. ' : '') + 'CQR is one number for everything a quarterback does, and 50 is exactly league average.';
    state.compMax = Math.max(4, ...qual.flatMap((x) => Object.values(x.components).map(Math.abs)));
    const sc = d.sanity_check;
    const ok = sc.pairs - sc.out_of_order.length;
    const byId = Object.fromEntries(d.qbs.map((x) => [x.id, x.name]));
    let note = `Qualified: at least ${d.qualify_dropbacks_per_team_game} dropbacks per team game (${qual.length} QBs). ` +
      `Sanity check: ${sc.pairs} pairs of qualified QBs where one is at least as good in passer rating, ANY/A, rushing yards, touchdowns, giveaways and sack rate; CQR ranks ${ok} of them in that order.`;
    if (sc.out_of_order.length) note += ' Exceptions: ' + sc.out_of_order.map((o) => `${byId[o.ranked_higher]} over ${byId[o.better_box]} by ${o.gap}`).join('; ') + '.';
    document.getElementById('board-note').textContent = note;
    document.getElementById('updated').textContent =
      `Data through ${dateText(d.last_game_date)} (${d.games_played} games). Rebuilt ${dateText(d.generated_at)}.`;
    renderHead();
    renderView();
  }

  function renderTrack(v) {
    if (!v) return;
    const t = document.getElementById('seasons-table');
    const head = el('thead', {}, el('tr', {}, ['Season', 'CQR leaders', 'AP MVP'].map((h) => el('th', { text: h }))));
    const body = el('tbody', {}, [...v.seasons].reverse().map((s) => el('tr', {},
      el('td', { text: s.season }),
      el('td', {}, s.top.slice(0, 3).map((p, i) => el('div', {}, `${i + 1}. ${p.name} `, el('span', { style: 'color:var(--muted)', text: fmt1(p.cqr) })))),
      el('td', {}, s.mvp ? [s.mvp, el('div', { style: 'color:var(--muted)', text: s.mvp_rank ? `CQR rank ${s.mvp_rank}` : '' })] : '–'))));
    t.replaceChildren(head, body);
    const ranked = v.seasons.filter((s) => s.mvp_rank);
    const top2 = ranked.filter((s) => s.mvp_rank <= 2).length;
    const others = ranked.filter((s) => s.mvp_rank > 2).map((s) => {
      const ahead = s.top.slice(0, s.mvp_rank - 1).map((p) => p.name);
      const list = ahead.length > 1 ? `${ahead.slice(0, -1).join(', ')} and ${ahead[ahead.length - 1]}` : ahead[0];
      return `${s.mvp} in ${s.season} ranked ${ordinal(s.mvp_rank)}, behind ${list}, who were more efficient per play that year`;
    });
    document.getElementById('mvp-note').textContent =
      `The AP MVP finished first or second in CQR in ${top2} of ${ranked.length} seasons.` + (others.length ? ` The exception: ${others.join('; ')}.` : '');
    const sc = v.sanity_check;
    const ok = sc.pairs - sc.out_of_order.length;
    const misses = sc.out_of_order.map((o) => {
      const why = WHY[`${o.season}|${o.ranked_higher}|${o.better_box}`];
      return `${o.ranked_higher} over ${o.better_box} in ${o.season} by ${o.gap}${why ? ` (${why})` : ''}`;
    });
    document.getElementById('sanity-hist').textContent =
      `A clear-cut pair is two qualified QBs in the same season where one is at least as good in passer rating, ANY/A, rushing yards per game, touchdowns per game, giveaways per game and sack rate. From ${v.seasons_tested[0]} to ${v.seasons_tested[1]} there were ${sc.pairs.toLocaleString()} of them, and CQR put ${ok.toLocaleString()} in the right order.` +
      (misses.length ? ` ${misses.length === 1 ? 'The exception' : 'The exceptions'}: ${misses.join('; ')}.` : '');
  }

  function renderHoldout(h) {
    if (!h) return;
    const b = document.getElementById('bench-table');
    const keys = ['split_half', 'year_to_year', 'win_pct'];
    const max = Object.fromEntries(keys.map((k) => [k, Math.max(...h.metrics.map((m) => m[k]))]));
    const mark = (m, i) => {
      if (!m.diff_ci) return null;
      const [lo, hi] = m.diff_ci[i];
      const t = lo > 0 ? ['▲', 'CQR ahead'] : hi < 0 ? ['▼', 'CQR behind'] : ['=', 'no significant difference'];
      return el('span', { title: `CQR minus ${m.label}: ${lo.toFixed(3)} to ${hi.toFixed(3)} (95% CI). ${t[1]}`, style: 'color:var(--muted);margin-left:4px', text: t[0] });
    };
    const cell = (m, k, i) => el('td', {}, m[k].toFixed(3), mark(m, i),
      el('span', { class: 'meter', style: `width:${Math.round((m[k] / max[k]) * 32)}px`, 'aria-hidden': 'true' }));
    b.replaceChildren(
      el('thead', {}, el('tr', {}, el('th', { class: 'left', text: 'Rating' }), el('th', { text: 'Split-half' }), el('th', { text: 'Year to year' }), el('th', { text: 'Wins' }))),
      el('tbody', {}, h.metrics.map((m) => el('tr', { class: m.key === 'cqr' ? 'us' : null },
        el('td', { class: 'left', text: m.label }), ...keys.map((k, i) => cell(m, k, i))))));
    document.getElementById('bench-verdict').textContent =
      'The honest summary: CQR beats passer rating and ANY/A within a season and on winning. Against raw EPA per play no significant difference was detected in any column, and against Total QBR only the link to winning is (narrowly) significant. No year-to-year gap is significant. CQR\'s edge is completeness and transparency, not a leap in accuracy. ' + (h.bootstrap || '');
  }

  function renderLive(d) {
    const box = document.getElementById('live-table'), note = document.getElementById('live-note');
    const lc = d.live_check;
    if (!lc) { box.replaceChildren(); note.textContent = 'The live check starts once four weeks have been played.'; return; }
    const current = d.season === state.index.current;
    note.textContent = current
      ? `CQR v${lc.version} was frozen on Oct 22, 2026. Each weekly rebuild re-scores it on ${d.season} so far: odd weeks vs. even weeks, and the first ${lc.early_through_week} weeks vs. the rest (${lc.qbs_split} and ${lc.qbs_early_late} QBs). Weeks 1-6 of 2026 were visible while the formula was built, so the check becomes fully independent as later weeks pile up. Early-season samples are small and noisy.`
      : `The same check on ${d.season}. That season was used while designing CQR, so it is not an independent test.`;
    const fmt = (v) => (v == null ? '–' : v.toFixed(3));
    box.replaceChildren(
      el('thead', {}, el('tr', {}, el('th', { class: 'left', text: 'Rating' }), el('th', { text: 'Odd vs. even weeks' }), el('th', { text: 'Early vs. late' }))),
      el('tbody', {}, lc.metrics.map((m) => el('tr', { class: m.key === 'cqr' ? 'us' : null },
        el('td', { class: 'left', text: m.label }), el('td', { text: fmt(m.split_half) }), el('td', { text: fmt(m.early_vs_late) })))));
  }

  async function loadSeason(season) {
    const body = document.getElementById('board-body');
    body.style.opacity = '0.5';
    try {
      state.data = await getJSON(String(season));
      state.season = season;
      state.open.clear();
      renderSeason();
      renderLive(state.data);
    } catch (err) {
      body.replaceChildren(el('tr', {}, el('td', { class: 'empty', colspan: COLS.length, text: err.message })));
    } finally {
      body.style.opacity = '';
    }
  }

  async function init() {
    window.addEventListener('resize', syncDetailWidth);
    state.showAll = recall('showAll', false);
    state.mode = recall('mode', 'season') === 'talent' ? 'talent' : 'season';
    const modeButtons = document.querySelectorAll('.modes button[data-mode]');
    const syncModes = () => modeButtons.forEach((btn) => btn.setAttribute('aria-pressed', String(btn.dataset.mode === state.mode)));
    syncModes();
    state.view = recall('view', 'list') === 'tiers' ? 'tiers' : 'list';
    syncViews();
    document.querySelectorAll('.views button').forEach((btn) => btn.addEventListener('click', () => {
      state.view = btn.dataset.view; store('view', state.view); syncViews(); if (state.data) renderView();
    }));
    modeButtons.forEach((btn) => btn.addEventListener('click', () => {
      state.mode = btn.dataset.mode; store('mode', state.mode); syncModes(); state.open.clear();
      if (state.data) renderSeason();
    }));
    const toggleAll = document.getElementById('show-all');
    toggleAll.checked = state.showAll;
    toggleAll.addEventListener('change', () => { state.showAll = toggleAll.checked; store('showAll', state.showAll); renderView(); });
    document.getElementById('search').addEventListener('input', (e) => { state.query = e.target.value; renderView(); });
    try {
      state.index = await getJSON('index');
    } catch (err) {
      document.getElementById('board-body').replaceChildren(el('tr', {}, el('td', { class: 'empty', colspan: COLS.length, text: err.message })));
      return;
    }
    const sel = document.getElementById('season');
    sel.replaceChildren(...state.index.seasons.map((s) => el('option', { value: s, text: s })));
    sel.value = state.index.current;
    sel.addEventListener('change', () => loadSeason(Number(sel.value)));
    await loadSeason(state.index.current);
    try { renderTrack(await getJSON('validation')); } catch (e) { /* track record is optional */ }
    try { renderHoldout(await getJSON('holdout')); } catch (e) { /* holdout results are optional */ }
  }

  init();
})();
