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
