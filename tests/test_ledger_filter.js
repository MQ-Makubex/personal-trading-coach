const test = require('node:test');
const assert = require('node:assert/strict');
const ledger = require('../templates/personal_site/ledger.js');

const dataset = {
  bounds: {minimum: '2026-06-01', maximum: '2026-07-10'},
  cycles: [
    {cycle_id: 'june', status: 'closed', stock_code: '000001', stock_name: '六月', close_date: '2026-06-30', realized_pnl_after_fees: -40, holding_days: 2},
    {cycle_id: 'july', status: 'closed', stock_code: '300260', stock_name: '新莱应材', close_date: '2026-07-10', realized_pnl_after_fees: 100, holding_days: 5},
    {cycle_id: 'open', status: 'open', stock_code: '301421', stock_name: '波长光电', close_date: '', realized_pnl_after_fees: null, holding_days: null}
  ],
  trades: [
    {trade_date: '2026-07-01', trade_time: '09:30:00', stock_code: '300260', stock_name: '新莱应材', side: 'BUY', quantity: 100, price: 10, amount: 1000, net_amount: -1002.5, fees: 2.5},
    {trade_date: '2026-06-30', trade_time: '10:00:00', stock_code: '000001', stock_name: '六月', side: 'SELL', quantity: 100, price: 9, amount: 900, net_amount: 897, fees: 3}
  ],
  adjustments: [
    {trade_date: '2026-07-03', stock_code: '300260', stock_name: '新莱应材', net_amount: 8}
  ]
};

test('month range uses cycle close dates and event dates', () => {
  const window = ledger.resolveWindow(new URLSearchParams('grain=month&period=2026-07'), dataset.bounds);
  const summary = ledger.summarizePeriod(dataset, window);
  assert.deepEqual([window.start, window.end], ['2026-07-01', '2026-07-31']);
  assert.equal(summary.realized_pnl, 108);
  assert.equal(summary.closed_cycles, 1);
  assert.equal(summary.fees, 2.5);
  assert.equal(summary.stock_count, 1);
});

test('week starts Monday and custom includes both endpoints', () => {
  const week = ledger.resolveWindow(new URLSearchParams('grain=week&period=2026-07-06'), dataset.bounds);
  assert.deepEqual([week.start, week.end], ['2026-07-06', '2026-07-12']);
  const custom = ledger.resolveWindow(new URLSearchParams('grain=custom&from=2026-07-01&to=2026-07-10'), dataset.bounds);
  assert.equal(ledger.summarizePeriod(dataset, custom).realized_pnl, 108);
});

test('invalid custom range reports a field error', () => {
  assert.throws(
    () => ledger.resolveWindow(new URLSearchParams('grain=custom&from=2026-07-10&to=2026-07-01'), dataset.bounds),
    /结束日期不能早于开始日期/
  );
});

test('invalid calendar dates report a field error', () => {
  assert.throws(
    () => ledger.resolveWindow(new URLSearchParams('grain=custom&from=2026-06-31&to=2026-07-01'), dataset.bounds),
    /请输入有效的开始和结束日期/
  );
  assert.throws(
    () => ledger.resolveWindow(new URLSearchParams('grain=custom&from=2026-13-01&to=2026-13-02'), dataset.bounds),
    /请输入有效的开始和结束日期/
  );
  assert.throws(
    () => ledger.resolveWindow(new URLSearchParams('grain=day&period=2026-02-30'), dataset.bounds),
    /日期格式无效/
  );
});

test('stock results add in-range adjustments to in-range closed cycles', () => {
  const window = ledger.resolveWindow(new URLSearchParams('grain=month&period=2026-07'), dataset.bounds);
  const rows = ledger.stockResults(dataset, window);
  assert.equal(rows[0].stock_code, '300260');
  assert.equal(rows[0].total_pnl, 108);
});

test('period shifting follows each calendar grain', () => {
  assert.equal(ledger.shiftPeriod('day', '2026-07-01', -1), '2026-06-30');
  assert.equal(ledger.shiftPeriod('week', '2026-07-06', 1), '2026-07-13');
  assert.equal(ledger.shiftPeriod('month', '2026-01', -1), '2025-12');
  assert.equal(ledger.shiftPeriod('year', '2026', 1), '2027');
});

test('empty periods distinguish no samples from no losses', () => {
  const empty = ledger.resolveWindow(new URLSearchParams('grain=day&period=2026-06-01'), dataset.bounds);
  const emptySummary = ledger.summarizePeriod(dataset, empty);
  assert.equal(emptySummary.win_rate_state, 'no_samples');
  assert.equal(emptySummary.profit_factor_state, 'no_samples');

  const winning = ledger.resolveWindow(new URLSearchParams('grain=month&period=2026-07'), dataset.bounds);
  assert.equal(ledger.summarizePeriod(dataset, winning).profit_factor_state, 'no_losses');
});

test('invalid custom URL restore preserves the last valid rendered list state', () => {
  const controllerDataset = {
    bounds: {minimum: '2026-07-01', maximum: '2026-07-10'},
    cycles: [
      {cycle_id: 'alpha', status: 'closed', stock_code: '000001', stock_name: 'Alpha', close_date: '2026-07-03', realized_pnl_after_fees: 30, holding_days: 1},
      {cycle_id: 'beta', status: 'closed', stock_code: '000002', stock_name: 'Beta', close_date: '2026-07-04', realized_pnl_after_fees: 20, holding_days: 1},
      {cycle_id: 'gamma', status: 'closed', stock_code: '000003', stock_name: 'Gamma', close_date: '2026-07-05', realized_pnl_after_fees: 10, holding_days: 1}
    ],
    trades: [
      {trade_date: '2026-07-03', trade_time: '09:30:00', stock_code: '000001', stock_name: 'Alpha', side: 'BUY', quantity: 100, price: 10, amount: 1000, net_amount: -1001, fees: 1},
      {trade_date: '2026-07-04', trade_time: '10:00:00', stock_code: '000002', stock_name: 'Beta', side: 'SELL', quantity: 200, price: 11, amount: 2200, net_amount: 2199, fees: 1},
      {trade_date: '2026-07-05', trade_time: '11:00:00', stock_code: '000003', stock_name: 'Gamma', side: 'BUY', quantity: 300, price: 12, amount: 3600, net_amount: -3601, fees: 1}
    ],
    adjustments: []
  };
  const dom = createLedgerDom(controllerDataset, '?grain=all&page=2&pnlpage=2');
  const ledgerPath = require.resolve('../templates/personal_site/ledger.js');
  const originalGlobals = {
    document: global.document,
    window: global.window,
    location: global.location,
    history: global.history
  };

  try {
    global.document = dom.document;
    global.window = dom.window;
    global.location = dom.window.location;
    global.history = dom.window.history;
    delete require.cache[ledgerPath];
    require(ledgerPath);
    dom.document.dispatchEvent({type: 'DOMContentLoaded'});

    assert.match(dom.tradeBody.innerHTML, /000002/);
    assert.match(dom.stockBody.innerHTML, /000002/);
    assert.equal(dom.tradeCount.textContent, '3 笔');
    assert.equal(dom.stockCount.textContent, '3 支');
    assert.equal(dom.tradePage.textContent, '2 / 3 页');
    assert.equal(dom.stockPage.textContent, '2 / 3 页');

    dom.setSearch('?grain=custom&from=2026-07-10&to=2026-07-01&q=foo&page=3&pnlq=bar&pnlpage=2');
    dom.window.dispatchEvent({type: 'popstate'});

    assert.match(dom.tradeBody.innerHTML, /000002/);
    assert.match(dom.stockBody.innerHTML, /000002/);
    assert.equal(dom.tradeCount.textContent, '3 笔');
    assert.equal(dom.stockCount.textContent, '3 支');
    assert.equal(dom.tradePage.textContent, '2 / 3 页');
    assert.equal(dom.stockPage.textContent, '2 / 3 页');
    assert.equal(dom.tradeSearch.value, '');
    assert.equal(dom.stockSearch.value, '');
    assert.equal(dom.customFields.hidden, false);
    assert.equal(dom.fromInput.value, '2026-07-10');
    assert.equal(dom.toInput.value, '2026-07-01');
    assert.equal(dom.errorNode.hidden, false);
    assert.match(dom.errorNode.textContent, /结束日期不能早于开始日期/);
  } finally {
    delete require.cache[ledgerPath];
    global.document = originalGlobals.document;
    global.window = originalGlobals.window;
    global.location = originalGlobals.location;
    global.history = originalGlobals.history;
  }
});

function createLedgerDom(ledgerDataset, initialSearch) {
  class FakeClassList {
    constructor() {
      this.values = new Set();
    }

    add(...names) {
      names.forEach(name => this.values.add(name));
    }

    remove(...names) {
      names.forEach(name => this.values.delete(name));
    }
  }

  class FakeElement {
    constructor(attributes = {}) {
      this.attributes = {};
      this.children = [];
      this.listeners = {};
      this.dataset = {};
      this.classList = new FakeClassList();
      this.textContent = '';
      this.innerHTML = '';
      this.value = '';
      this.hidden = false;
      this.disabled = false;
      Object.entries(attributes).forEach(([name, value]) => this.setAttribute(name, value));
    }

    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name === 'id') this.id = String(value);
      if (name.startsWith('data-')) {
        const key = name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
        this.dataset[key] = String(value);
      }
    }

    append(...children) {
      children.forEach(child => {
        child.parent = this;
        this.children.push(child);
      });
    }

    addEventListener(type, handler) {
      this.listeners[type] = this.listeners[type] || [];
      this.listeners[type].push(handler);
    }

    dispatchEvent(event) {
      (this.listeners[event.type] || []).forEach(handler => handler(event));
    }

    querySelector(selector) {
      return this.querySelectorAll(selector)[0] || null;
    }

    querySelectorAll(selector) {
      const parts = selector.trim().split(/\s+/);
      let candidates = [this];
      parts.forEach(part => {
        candidates = candidates.flatMap(candidate => descendants(candidate).filter(node => matches(node, part)));
      });
      return candidates;
    }
  }

  class FakeDocument extends FakeElement {
    constructor(root, dataNode) {
      super();
      this.append(root, dataNode);
    }
  }

  function descendants(node) {
    return node.children.flatMap(child => [child, ...descendants(child)]);
  }

  function matches(node, selector) {
    if (selector.startsWith('#')) return node.id === selector.slice(1);
    const attr = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
    if (!attr) return false;
    const [, name, value] = attr;
    return Object.prototype.hasOwnProperty.call(node.attributes, name) && (value == null || node.attributes[name] === value);
  }

  const root = new FakeElement({'data-ledger-app': '', 'data-page-size': '1'});
  const dataNode = new FakeElement({id: 'ledgerData'});
  dataNode.textContent = JSON.stringify(ledgerDataset);

  const grainButtons = ['all', 'day', 'week', 'month', 'year', 'custom'].map(grain => new FakeElement({'data-ledger-grain': grain}));
  const sideButtons = ['all', 'buy', 'sell'].map(side => new FakeElement({'data-ledger-filter': side}));
  const previousPeriod = new FakeElement({'data-ledger-prev': ''});
  const nextPeriod = new FakeElement({'data-ledger-next': ''});
  const periodLabel = new FakeElement({'data-ledger-period-label': ''});
  const customFields = new FakeElement({'data-ledger-custom': ''});
  customFields.hidden = true;
  const fromInput = new FakeElement({id: 'ledgerFrom'});
  const toInput = new FakeElement({id: 'ledgerTo'});
  const applyCustom = new FakeElement({'data-ledger-apply-custom': ''});
  const errorNode = new FakeElement({'data-ledger-error': ''});
  errorNode.hidden = true;
  const tradeSearch = new FakeElement({id: 'ledgerSearch'});
  const stockSearch = new FakeElement({id: 'pnlSearch'});
  const tradeBody = new FakeElement({'data-ledger-trade-body': ''});
  const stockBody = new FakeElement({'data-ledger-stock-body': ''});
  const tradeEmpty = new FakeElement({id: 'ledgerEmpty'});
  const stockEmpty = new FakeElement({id: 'pnlEmpty'});
  const tradePage = new FakeElement({id: 'ledgerPage'});
  const stockPage = new FakeElement({id: 'pnlPage'});
  const tradeCount = new FakeElement({'data-ledger-trade-count': ''});
  const stockCount = new FakeElement({'data-ledger-stock-count': ''});
  const tradeSection = new FakeElement({'data-ledger-trades': ''});
  const tradePrevious = new FakeElement({'data-page-prev': ''});
  const tradeNext = new FakeElement({'data-page-next': ''});
  const stockSection = new FakeElement({'data-ledger-stocks': ''});
  const stockPrevious = new FakeElement({'data-pnl-page-prev': ''});
  const stockNext = new FakeElement({'data-pnl-page-next': ''});
  const metrics = [
    'data-period-realized',
    'data-period-cycles',
    'data-period-win-rate',
    'data-period-profit-factor',
    'data-period-fees',
    'data-period-stocks'
  ].map(name => new FakeElement({[name]: ''}));

  customFields.append(fromInput, toInput, applyCustom);
  tradeSection.append(tradeSearch, ...sideButtons, tradeBody, tradeEmpty, tradePage, tradePrevious, tradeNext, tradeCount);
  stockSection.append(stockSearch, stockBody, stockEmpty, stockPage, stockPrevious, stockNext, stockCount);
  root.append(...grainButtons, previousPeriod, nextPeriod, periodLabel, customFields, errorNode, ...metrics, tradeSection, stockSection);

  const document = new FakeDocument(root, dataNode);
  const listeners = {};
  const location = {pathname: '/ledger.html', search: initialSearch};
  const setSearch = search => {
    location.search = search;
  };
  const history = {
    pushState(_state, _title, url) {
      location.search = url.includes('?') ? url.slice(url.indexOf('?')) : '';
    },
    replaceState(_state, _title, url) {
      location.search = url.includes('?') ? url.slice(url.indexOf('?')) : '';
    }
  };
  const window = {
    location,
    history,
    addEventListener(type, handler) {
      listeners[type] = listeners[type] || [];
      listeners[type].push(handler);
    },
    dispatchEvent(event) {
      (listeners[event.type] || []).forEach(handler => handler(event));
    }
  };

  return {
    document,
    window,
    setSearch,
    customFields,
    fromInput,
    toInput,
    errorNode,
    tradeSearch,
    stockSearch,
    tradeBody,
    stockBody,
    tradeCount,
    stockCount,
    tradePage,
    stockPage
  };
}
