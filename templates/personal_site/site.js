(() => {
  const params = new URLSearchParams(location.search);

  function normalize(value) {
    return String(value || '').trim().toLowerCase();
  }

  function updateUrl(values) {
    const next = new URLSearchParams(location.search);
    Object.entries(values).forEach(([key, value]) => {
      if (value && value !== 'all' && value !== '1') next.set(key, value);
      else next.delete(key);
    });
    const query = next.toString();
    try {
      history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}`);
    } catch (_) {
      // Static file viewers may reject history updates; filtering still works.
    }
  }

  function setPressed(buttons, active, dataKey) {
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset[dataKey] === active)));
  }

  function paginate(items, page, pageSize) {
    const pages = Math.max(1, Math.ceil(items.length / pageSize));
    const safePage = Math.min(Math.max(page, 1), pages);
    const start = (safePage - 1) * pageSize;
    return {pages, page: safePage, start, visible: items.slice(start, start + pageSize)};
  }

  function showPage(allItems, filteredItems, result, empty, label, previous, next) {
    const visible = new Set(result.visible);
    allItems.forEach(item => { item.hidden = !visible.has(item); });
    if (empty) empty.hidden = filteredItems.length !== 0;
    if (label) label.textContent = filteredItems.length ? `${result.page} / ${result.pages} 页` : '0 / 0 页';
    if (previous) previous.disabled = result.page <= 1;
    if (next) next.disabled = result.page >= result.pages;
  }

  function initTimeline() {
    const root = document.querySelector('[data-timeline-app]');
    if (!root) return;
    const items = Array.from(root.querySelectorAll('[data-timeline-item]'));
    const categoryButtons = Array.from(root.querySelectorAll('[data-timeline-filter]'));
    const dateButtons = Array.from(root.querySelectorAll('[data-calendar-date]'));
    const queryInput = root.querySelector('#timelineSearch');
    const stockInput = root.querySelector('#timelineStock');
    const status = root.querySelector('#timelineStatus');
    const empty = root.querySelector('#timelineEmpty');
    const pageLabel = root.querySelector('#timelinePage');
    const previous = root.querySelector('[data-page-prev]');
    const next = root.querySelector('[data-page-next]');
    const pageSize = Number(root.dataset.pageSize) || 8;
    let category = params.get('type') || 'all';
    let date = params.get('date') || 'all';
    let query = params.get('q') || '';
    let stock = params.get('stock') || '';
    let page = Number(params.get('page')) || 1;
    queryInput.value = query;
    stockInput.value = stock;

    function render() {
      const normalizedQuery = normalize(query);
      const normalizedStock = normalize(stock);
      const filtered = items.filter(item => {
        const categoryOk = category === 'all' || item.dataset.category === category;
        const dateOk = date === 'all' || item.dataset.date === date;
        const queryOk = !normalizedQuery || normalize(item.dataset.search).includes(normalizedQuery);
        const stockOk = !normalizedStock || normalize(item.dataset.stocks).includes(normalizedStock);
        return categoryOk && dateOk && queryOk && stockOk;
      });
      const result = paginate(filtered, page, pageSize);
      page = result.page;
      showPage(items, filtered, result, empty, pageLabel, previous, next);
      status.textContent = filtered.length
        ? `显示 ${result.start + 1}-${Math.min(result.start + pageSize, filtered.length)} / ${filtered.length} 篇`
        : '没有匹配结果';
      setPressed(categoryButtons, category, 'timelineFilter');
      setPressed(dateButtons, date, 'calendarDate');
      updateUrl({type: category, date, q: query, stock, page: String(page)});
    }

    categoryButtons.forEach(button => button.addEventListener('click', () => {
      category = button.dataset.timelineFilter;
      page = 1;
      render();
    }));
    dateButtons.forEach(button => button.addEventListener('click', () => {
      date = button.dataset.calendarDate;
      page = 1;
      render();
    }));
    queryInput.addEventListener('input', () => { query = queryInput.value; page = 1; render(); });
    stockInput.addEventListener('input', () => { stock = stockInput.value; page = 1; render(); });
    previous.addEventListener('click', () => { page -= 1; render(); });
    next.addEventListener('click', () => { page += 1; render(); });
    render();
  }

  function initStories() {
    const root = document.querySelector('[data-story-app]');
    if (!root) return;
    const items = Array.from(root.querySelectorAll('[data-story-item]'));
    const buttons = Array.from(root.querySelectorAll('[data-story-filter]'));
    const queryInput = root.querySelector('#storySearch');
    const empty = root.querySelector('#storyEmpty');
    const pageLabel = root.querySelector('#storyPage');
    const previous = root.querySelector('[data-page-prev]');
    const next = root.querySelector('[data-page-next]');
    const pageSize = Number(root.dataset.pageSize) || 12;
    let status = params.get('status') || 'current';
    let query = params.get('q') || '';
    let page = Number(params.get('page')) || 1;
    queryInput.value = query;

    function render() {
      const normalizedQuery = normalize(query);
      const filtered = items.filter(item => {
        const statusOk = status === 'all' || item.dataset.status === status;
        const queryOk = !normalizedQuery || normalize(item.dataset.search).includes(normalizedQuery);
        return statusOk && queryOk;
      });
      const result = paginate(filtered, page, pageSize);
      page = result.page;
      showPage(items, filtered, result, empty, pageLabel, previous, next);
      setPressed(buttons, status, 'storyFilter');
      updateUrl({status, q: query, page: String(page)});
    }

    buttons.forEach(button => button.addEventListener('click', () => {
      status = button.dataset.storyFilter;
      page = 1;
      render();
    }));
    queryInput.addEventListener('input', () => { query = queryInput.value; page = 1; render(); });
    previous.addEventListener('click', () => { page -= 1; render(); });
    next.addEventListener('click', () => { page += 1; render(); });
    render();
  }

  function initLedger() {
    const root = document.querySelector('[data-ledger-app]');
    if (!root) return;
    const items = Array.from(root.querySelectorAll('[data-ledger-row]'));
    const buttons = Array.from(root.querySelectorAll('[data-ledger-filter]'));
    const queryInput = root.querySelector('#ledgerSearch');
    const empty = root.querySelector('#ledgerEmpty');
    const pageLabel = root.querySelector('#ledgerPage');
    const previous = root.querySelector('[data-page-prev]');
    const next = root.querySelector('[data-page-next]');
    const pageSize = Number(root.dataset.pageSize) || 20;
    let side = params.get('side') || 'all';
    let query = params.get('q') || '';
    let page = Number(params.get('page')) || 1;
    queryInput.value = query;

    function render() {
      const normalizedQuery = normalize(query);
      const filtered = items.filter(item => {
        const sideOk = side === 'all' || item.dataset.side === side;
        const queryOk = !normalizedQuery || normalize(item.dataset.search).includes(normalizedQuery);
        return sideOk && queryOk;
      });
      const result = paginate(filtered, page, pageSize);
      page = result.page;
      showPage(items, filtered, result, empty, pageLabel, previous, next);
      setPressed(buttons, side, 'ledgerFilter');
      updateUrl({side, q: query, page: String(page)});
    }

    buttons.forEach(button => button.addEventListener('click', () => {
      side = button.dataset.ledgerFilter;
      page = 1;
      render();
    }));
    queryInput.addEventListener('input', () => { query = queryInput.value; page = 1; render(); });
    previous.addEventListener('click', () => { page -= 1; render(); });
    next.addEventListener('click', () => { page += 1; render(); });
    render();
  }

  function initPnlTable() {
    const root = document.querySelector('[data-pnl-app]');
    if (!root) return;
    const items = Array.from(root.querySelectorAll('[data-pnl-row]'));
    const queryInput = root.querySelector('#pnlSearch');
    const empty = root.querySelector('#pnlEmpty');
    const pageLabel = root.querySelector('#pnlPage');
    const previous = root.querySelector('[data-page-prev]');
    const next = root.querySelector('[data-page-next]');
    const pageSize = Number(root.dataset.pageSize) || 20;
    let query = params.get('pnlq') || '';
    let page = Number(params.get('pnlpage')) || 1;
    queryInput.value = query;

    function render() {
      const normalizedQuery = normalize(query);
      const filtered = items.filter(item => !normalizedQuery || normalize(item.dataset.search).includes(normalizedQuery));
      const result = paginate(filtered, page, pageSize);
      page = result.page;
      showPage(items, filtered, result, empty, pageLabel, previous, next);
      updateUrl({pnlq: query, pnlpage: String(page)});
    }

    queryInput.addEventListener('input', () => { query = queryInput.value; page = 1; render(); });
    previous.addEventListener('click', () => { page -= 1; render(); });
    next.addEventListener('click', () => { page += 1; render(); });
    render();
  }

  function initRules() {
    const root = document.querySelector('[data-rules-app]');
    if (!root) return;
    const buttons = Array.from(root.querySelectorAll('[data-rule-tab]'));
    const panels = Array.from(root.querySelectorAll('[data-rule-panel]'));
    let section = params.get('section') || buttons[0]?.dataset.ruleTab || '';

    function render() {
      buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.ruleTab === section)));
      panels.forEach(panel => { panel.hidden = panel.dataset.rulePanel !== section; });
      updateUrl({section});
    }
    buttons.forEach(button => button.addEventListener('click', () => {
      section = button.dataset.ruleTab;
      render();
    }));
    render();
  }

  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      const input = document.querySelector('#globalSearch');
      if (!input) return;
      event.preventDefault();
      input.focus();
      input.select();
    }
  });

  initTimeline();
  initStories();
  initLedger();
  initPnlTable();
  initRules();
})();
