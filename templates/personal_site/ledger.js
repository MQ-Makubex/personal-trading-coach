(function (global) {
  'use strict';

  const round2 = value => Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
  const inRange = (value, window) => !window.start || (value >= window.start && value <= window.end);
  const iso = value => new Date(`${value}T00:00:00Z`);
  const isoText = value => value.toISOString().slice(0, 10);
  const validDate = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = iso(value);
    return !Number.isNaN(parsed.getTime()) && isoText(parsed) === value;
  };

  function defaultPeriod(grain, maximum) {
    if (grain === 'day') return maximum;
    if (grain === 'week') {
      const current = iso(maximum);
      const weekday = (current.getUTCDay() + 6) % 7;
      current.setUTCDate(current.getUTCDate() - weekday);
      return isoText(current);
    }
    if (grain === 'month') return maximum.slice(0, 7);
    if (grain === 'year') return maximum.slice(0, 4);
    throw new Error('不支持的时间粒度');
  }

  function rangeForPeriod(grain, period) {
    if ((grain === 'day' || grain === 'week') && !validDate(period)) throw new Error('日期格式无效');
    if (grain === 'day') return {grain, period, label: period, start: period, end: period};
    if (grain === 'week') {
      const startDate = iso(period);
      const weekday = (startDate.getUTCDay() + 6) % 7;
      startDate.setUTCDate(startDate.getUTCDate() - weekday);
      const endDate = new Date(startDate);
      endDate.setUTCDate(endDate.getUTCDate() + 6);
      const start = isoText(startDate);
      const end = isoText(endDate);
      return {grain, period: start, label: `${start} 至 ${end}`, start, end};
    }
    if (grain === 'month') {
      if (!/^\d{4}-\d{2}$/.test(period)) throw new Error('月份格式无效');
      const [year, month] = period.split('-').map(Number);
      if (month < 1 || month > 12) throw new Error('月份格式无效');
      const end = new Date(Date.UTC(year, month, 0));
      return {grain, period, label: period, start: `${period}-01`, end: isoText(end)};
    }
    if (grain === 'year') {
      if (!/^\d{4}$/.test(period)) throw new Error('年份格式无效');
      return {grain, period, label: period, start: `${period}-01-01`, end: `${period}-12-31`};
    }
    throw new Error('不支持的时间粒度');
  }

  function shiftPeriod(grain, period, delta) {
    if (grain === 'day' || grain === 'week') {
      const current = iso(period);
      current.setUTCDate(current.getUTCDate() + delta * (grain === 'week' ? 7 : 1));
      return isoText(current);
    }
    if (grain === 'month') {
      const [year, month] = period.split('-').map(Number);
      const current = new Date(Date.UTC(year, month - 1 + delta, 1));
      return `${current.getUTCFullYear()}-${String(current.getUTCMonth() + 1).padStart(2, '0')}`;
    }
    if (grain === 'year') return String(Number(period) + delta);
    throw new Error('当前粒度不支持前后导航');
  }

  function resolveWindow(params, bounds) {
    const grain = params.get('grain') || 'all';
    if (grain === 'all') return {grain, period: '', label: '全部历史', start: null, end: null};
    if (!bounds || !bounds.minimum || !bounds.maximum) throw new Error('底账没有可用日期');
    if (grain === 'custom') {
      const start = params.get('from') || '';
      const end = params.get('to') || '';
      if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) {
        throw new Error('请输入完整的开始和结束日期');
      }
      if (!validDate(start) || !validDate(end)) throw new Error('请输入有效的开始和结束日期');
      if (end < start) throw new Error('结束日期不能早于开始日期');
      if (start < bounds.minimum || end > bounds.maximum) throw new Error('所选日期超出底账日期范围');
      return {grain, period: '', label: `${start} 至 ${end}`, start, end};
    }
    const period = params.get('period') || defaultPeriod(grain, bounds.maximum);
    const window = rangeForPeriod(grain, period);
    if (window.end < bounds.minimum || window.start > bounds.maximum) throw new Error('所选周期超出底账日期范围');
    return window;
  }

  function summarizePeriod(dataset, window) {
    const cycles = dataset.cycles.filter(row => row.status === 'closed' && inRange(row.close_date, window));
    const trades = dataset.trades.filter(row => inRange(row.trade_date, window));
    const adjustments = dataset.adjustments.filter(row => inRange(row.trade_date, window));
    const wins = cycles.filter(row => Number(row.realized_pnl_after_fees) > 0);
    const losses = cycles.filter(row => Number(row.realized_pnl_after_fees) < 0);
    const grossWins = wins.reduce((sum, row) => sum + Number(row.realized_pnl_after_fees), 0);
    const grossLosses = Math.abs(losses.reduce((sum, row) => sum + Number(row.realized_pnl_after_fees), 0));
    return {
      realized_pnl: round2(
        cycles.reduce((sum, row) => sum + Number(row.realized_pnl_after_fees || 0), 0)
          + adjustments.reduce((sum, row) => sum + Number(row.net_amount || 0), 0)
      ),
      closed_cycles: cycles.length,
      win_rate: cycles.length ? round2(wins.length / cycles.length * 100) : null,
      win_rate_state: cycles.length ? 'value' : 'no_samples',
      profit_factor: losses.length ? round2(grossWins / grossLosses) : null,
      profit_factor_state: !cycles.length ? 'no_samples' : !losses.length ? 'no_losses' : 'value',
      fees: round2(trades.reduce((sum, row) => sum + Number(row.fees || 0), 0)),
      stock_count: new Set(trades.map(row => row.stock_code).filter(code => /^\d{6}$/.test(code))).size
    };
  }

  function stockResults(dataset, window) {
    const rows = new Map();
    const ensure = (code, name) => {
      if (!rows.has(code)) {
        rows.set(code, {
          stock_code: code,
          stock_name: name || '',
          cycle_pnl: 0,
          cash_adjustments: 0,
          total_pnl: 0,
          closed_cycles: 0
        });
      }
      return rows.get(code);
    };
    dataset.cycles.filter(row => row.status === 'closed' && inRange(row.close_date, window)).forEach(row => {
      const item = ensure(row.stock_code, row.stock_name);
      item.cycle_pnl += Number(row.realized_pnl_after_fees || 0);
      item.closed_cycles += 1;
    });
    dataset.adjustments.filter(row => inRange(row.trade_date, window)).forEach(row => {
      ensure(row.stock_code, row.stock_name).cash_adjustments += Number(row.net_amount || 0);
    });
    return Array.from(rows.values())
      .map(row => Object.assign({}, row, {
        cycle_pnl: round2(row.cycle_pnl),
        cash_adjustments: round2(row.cash_adjustments),
        total_pnl: round2(row.cycle_pnl + row.cash_adjustments)
      }))
      .sort((left, right) => Math.abs(right.total_pnl) - Math.abs(left.total_pnl) || left.stock_code.localeCompare(right.stock_code));
  }

  function initLedgerPage() {
    const root = document.querySelector('[data-ledger-app]');
    const dataNode = document.querySelector('#ledgerData');
    if (!root || !dataNode) return;

    let dataset;
    try {
      dataset = JSON.parse(dataNode.textContent);
    } catch (_) {
      return;
    }

    const pageSize = Number(root.dataset.pageSize) || 20;
    const grainButtons = Array.from(root.querySelectorAll('[data-ledger-grain]'));
    const sideButtons = Array.from(root.querySelectorAll('[data-ledger-filter]'));
    const previousPeriod = root.querySelector('[data-ledger-prev]');
    const nextPeriod = root.querySelector('[data-ledger-next]');
    const periodLabel = root.querySelector('[data-ledger-period-label]');
    const customFields = root.querySelector('[data-ledger-custom]');
    const fromInput = root.querySelector('#ledgerFrom');
    const toInput = root.querySelector('#ledgerTo');
    const applyCustom = root.querySelector('[data-ledger-apply-custom]');
    const errorNode = root.querySelector('[data-ledger-error]');
    const tradeQuery = root.querySelector('#ledgerSearch');
    const stockQuery = root.querySelector('#pnlSearch');
    const tradeBody = root.querySelector('[data-ledger-trade-body]');
    const stockBody = root.querySelector('[data-ledger-stock-body]');
    const tradeEmpty = root.querySelector('#ledgerEmpty');
    const stockEmpty = root.querySelector('#pnlEmpty');
    const tradePageLabel = root.querySelector('#ledgerPage');
    const stockPageLabel = root.querySelector('#pnlPage');
    const tradePrevious = root.querySelector('[data-ledger-trades] [data-page-prev]');
    const tradeNext = root.querySelector('[data-ledger-trades] [data-page-next]');
    const stockPrevious = root.querySelector('[data-pnl-page-prev]');
    const stockNext = root.querySelector('[data-pnl-page-next]');
    const tradeCount = root.querySelector('[data-ledger-trade-count]');
    const stockCount = root.querySelector('[data-ledger-stock-count]');
    const metricTargets = {
      realized_pnl: root.querySelector('[data-period-realized]'),
      closed_cycles: root.querySelector('[data-period-cycles]'),
      win_rate: root.querySelector('[data-period-win-rate]'),
      profit_factor: root.querySelector('[data-period-profit-factor]'),
      fees: root.querySelector('[data-period-fees]'),
      stock_count: root.querySelector('[data-period-stocks]')
    };
    let lastValidWindow = resolveWindow(new URLSearchParams(), dataset.bounds);
    let state = {side: 'all', q: '', page: 1, pnlq: '', pnlpage: 1};

    const escapeHtml = value => String(value == null ? '' : value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
    const normalize = value => String(value || '').trim().toLowerCase();
    const safePage = value => Math.max(1, Number.parseInt(value, 10) || 1);
    const moneyText = value => {
      const amount = Number(value || 0);
      return `${amount < 0 ? '-' : ''}¥${Math.abs(amount).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    };
    const numberText = value => Number(value || 0).toLocaleString('zh-CN', {maximumFractionDigits: 4});
    const valueClass = value => Number(value || 0) >= 0 ? 'gain' : 'loss';

    function paginate(rows, requestedPage) {
      const pages = Math.max(1, Math.ceil(rows.length / pageSize));
      const page = Math.min(Math.max(requestedPage, 1), pages);
      const start = (page - 1) * pageSize;
      return {page, pages, rows: rows.slice(start, start + pageSize)};
    }

    function showError(message) {
      errorNode.textContent = message || '';
      errorNode.hidden = !message;
    }

    function readListState(params) {
      const side = params.get('side') || 'all';
      state = {
        side: ['all', 'buy', 'sell'].includes(side) ? side : 'all',
        q: params.get('q') || '',
        page: safePage(params.get('page')),
        pnlq: params.get('pnlq') || '',
        pnlpage: safePage(params.get('pnlpage'))
      };
      tradeQuery.value = state.q;
      stockQuery.value = state.pnlq;
    }

    function setQueryValue(params, key, value, defaultValue = '') {
      if (value && value !== defaultValue) params.set(key, String(value));
      else params.delete(key);
    }

    function writeUrl(mode) {
      const params = new URLSearchParams(location.search);
      ['grain', 'period', 'from', 'to'].forEach(key => params.delete(key));
      if (lastValidWindow.grain === 'custom') {
        params.set('grain', 'custom');
        params.set('from', lastValidWindow.start);
        params.set('to', lastValidWindow.end);
      } else if (lastValidWindow.grain !== 'all') {
        params.set('grain', lastValidWindow.grain);
        params.set('period', lastValidWindow.period);
      }
      setQueryValue(params, 'side', state.side, 'all');
      setQueryValue(params, 'q', state.q);
      setQueryValue(params, 'page', state.page === 1 ? '' : state.page);
      setQueryValue(params, 'pnlq', state.pnlq);
      setQueryValue(params, 'pnlpage', state.pnlpage === 1 ? '' : state.pnlpage);
      const query = params.toString();
      try {
        history[mode === 'push' ? 'pushState' : 'replaceState'](null, '', `${location.pathname}${query ? `?${query}` : ''}`);
      } catch (_) {
        // Static file viewers may reject history updates; the active view still works.
      }
    }

    function updateMetric(node, text, value) {
      node.textContent = text;
      node.classList.remove('gain', 'loss', 'pending');
      if (value == null) node.classList.add('pending');
      else node.classList.add(valueClass(value));
    }

    function renderMetrics(window) {
      const summary = summarizePeriod(dataset, window);
      updateMetric(metricTargets.realized_pnl, moneyText(summary.realized_pnl), summary.realized_pnl);
      updateMetric(metricTargets.closed_cycles, numberText(summary.closed_cycles), null);
      updateMetric(
        metricTargets.win_rate,
        summary.win_rate_state === 'no_samples' ? '暂无样本' : `${summary.win_rate.toFixed(2)}%`,
        null
      );
      updateMetric(
        metricTargets.profit_factor,
        summary.profit_factor_state === 'no_samples'
          ? '暂无样本'
          : summary.profit_factor_state === 'no_losses' ? '无亏损周期' : summary.profit_factor.toFixed(2),
        null
      );
      updateMetric(metricTargets.fees, moneyText(summary.fees), null);
      updateMetric(metricTargets.stock_count, numberText(summary.stock_count), null);
    }

    function renderTrades(window) {
      const query = normalize(state.q);
      const rows = dataset.trades.filter(row => {
        const dateOk = !window.start || (row.trade_date >= window.start && row.trade_date <= window.end);
        const sideOk = state.side === 'all' || normalize(row.side) === state.side;
        const search = normalize(`${row.stock_code} ${row.stock_name} ${row.trade_date}`);
        return dateOk && sideOk && (!query || search.includes(query));
      });
      const result = paginate(rows, state.page);
      state.page = result.page;
      tradeBody.innerHTML = result.rows.map(row => {
        const side = normalize(row.side);
        const label = side === 'buy' ? '买入' : '卖出';
        return `<tr><td><span class="mono">${escapeHtml(row.trade_date)}</span><small>${escapeHtml(row.trade_time)}</small></td>`
          + `<td><a href="stocks/${escapeHtml(row.stock_code)}.html"><strong>${escapeHtml(row.stock_name)}</strong><small class="mono">${escapeHtml(row.stock_code)}</small></a></td>`
          + `<td><span class="side-label ${side}">${label}</span></td><td class="num">${numberText(row.quantity)}</td>`
          + `<td class="num">${Number(row.price || 0).toFixed(3)}</td><td class="num">${moneyText(row.amount)}</td><td class="num">${moneyText(row.fees)}</td></tr>`;
      }).join('');
      tradeEmpty.hidden = rows.length !== 0;
      tradePageLabel.textContent = rows.length ? `${result.page} / ${result.pages} 页` : '0 / 0 页';
      tradePrevious.disabled = result.page <= 1;
      tradeNext.disabled = result.page >= result.pages;
      tradeCount.textContent = `${rows.length} 笔`;
      sideButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.ledgerFilter === state.side)));
    }

    function renderStocks(window) {
      const query = normalize(state.pnlq);
      const rows = stockResults(dataset, window).filter(row => !query || normalize(`${row.stock_code} ${row.stock_name}`).includes(query));
      const result = paginate(rows, state.pnlpage);
      state.pnlpage = result.page;
      stockBody.innerHTML = result.rows.map(row => `<tr><td><a href="stocks/${escapeHtml(row.stock_code)}.html"><strong>${escapeHtml(row.stock_name)}</strong><small class="mono">${escapeHtml(row.stock_code)}</small></a></td>`
        + `<td class="num">${numberText(row.closed_cycles)}</td><td class="num ${valueClass(row.cycle_pnl)}">${moneyText(row.cycle_pnl)}</td>`
        + `<td class="num ${valueClass(row.cash_adjustments)}">${moneyText(row.cash_adjustments)}</td><td class="num ${valueClass(row.total_pnl)}">${moneyText(row.total_pnl)}</td></tr>`).join('');
      stockEmpty.hidden = rows.length !== 0;
      stockPageLabel.textContent = rows.length ? `${result.page} / ${result.pages} 页` : '0 / 0 页';
      stockPrevious.disabled = result.page <= 1;
      stockNext.disabled = result.page >= result.pages;
      stockCount.textContent = `${rows.length} 支`;
    }

    function shiftedWindowExists(delta) {
      if (!['day', 'week', 'month', 'year'].includes(lastValidWindow.grain)) return false;
      const params = new URLSearchParams();
      params.set('grain', lastValidWindow.grain);
      params.set('period', shiftPeriod(lastValidWindow.grain, lastValidWindow.period, delta));
      try {
        resolveWindow(params, dataset.bounds);
        return true;
      } catch (_) {
        return false;
      }
    }

    function render(window) {
      grainButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.ledgerGrain === window.grain)));
      periodLabel.textContent = window.label;
      customFields.hidden = window.grain !== 'custom';
      if (window.grain === 'custom') {
        fromInput.value = window.start;
        toInput.value = window.end;
      }
      previousPeriod.disabled = !shiftedWindowExists(-1);
      nextPeriod.disabled = !shiftedWindowExists(1);
      renderMetrics(window);
      renderTrades(window);
      renderStocks(window);
    }

    function commitWindow(window, historyMode) {
      lastValidWindow = window;
      state.page = 1;
      state.pnlpage = 1;
      showError('');
      render(window);
      writeUrl(historyMode);
    }

    function chooseGrain(grain) {
      const params = new URLSearchParams();
      params.set('grain', grain);
      if (grain === 'custom') {
        params.set('from', lastValidWindow.start && lastValidWindow.start > dataset.bounds.minimum ? lastValidWindow.start : dataset.bounds.minimum);
        params.set('to', lastValidWindow.end && lastValidWindow.end < dataset.bounds.maximum ? lastValidWindow.end : dataset.bounds.maximum);
      }
      try {
        commitWindow(resolveWindow(params, dataset.bounds), 'push');
      } catch (error) {
        showError(error.message);
      }
    }

    grainButtons.forEach(button => button.addEventListener('click', () => chooseGrain(button.dataset.ledgerGrain)));
    [previousPeriod, nextPeriod].forEach((button, index) => button.addEventListener('click', () => {
      const delta = index === 0 ? -1 : 1;
      const params = new URLSearchParams();
      params.set('grain', lastValidWindow.grain);
      params.set('period', shiftPeriod(lastValidWindow.grain, lastValidWindow.period, delta));
      commitWindow(resolveWindow(params, dataset.bounds), 'push');
    }));
    applyCustom.addEventListener('click', () => {
      const params = new URLSearchParams();
      params.set('grain', 'custom');
      params.set('from', fromInput.value);
      params.set('to', toInput.value);
      try {
        commitWindow(resolveWindow(params, dataset.bounds), 'push');
      } catch (error) {
        showError(error.message);
      }
    });
    sideButtons.forEach(button => button.addEventListener('click', () => {
      state.side = button.dataset.ledgerFilter;
      state.page = 1;
      render(lastValidWindow);
      writeUrl('push');
    }));
    tradeQuery.addEventListener('input', () => {
      state.q = tradeQuery.value;
      state.page = 1;
      render(lastValidWindow);
      writeUrl('push');
    });
    stockQuery.addEventListener('input', () => {
      state.pnlq = stockQuery.value;
      state.pnlpage = 1;
      render(lastValidWindow);
      writeUrl('push');
    });
    tradePrevious.addEventListener('click', () => { state.page -= 1; render(lastValidWindow); writeUrl('push'); });
    tradeNext.addEventListener('click', () => { state.page += 1; render(lastValidWindow); writeUrl('push'); });
    stockPrevious.addEventListener('click', () => { state.pnlpage -= 1; render(lastValidWindow); writeUrl('push'); });
    stockNext.addEventListener('click', () => { state.pnlpage += 1; render(lastValidWindow); writeUrl('push'); });

    function restoreFromUrl() {
      const params = new URLSearchParams(location.search);
      readListState(params);
      try {
        lastValidWindow = resolveWindow(params, dataset.bounds);
        showError('');
        render(lastValidWindow);
        writeUrl('replace');
      } catch (error) {
        showError(error.message);
        render(lastValidWindow);
        if (params.get('grain') === 'custom') {
          customFields.hidden = false;
          fromInput.value = params.get('from') || '';
          toInput.value = params.get('to') || '';
          grainButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.ledgerGrain === 'custom')));
        }
      }
    }

    window.addEventListener('popstate', restoreFromUrl);
    restoreFromUrl();
  }

  const api = {resolveWindow, shiftPeriod, summarizePeriod, stockResults};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.PersonalSiteLedger = api;
  if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initLedgerPage);
})(globalThis);
