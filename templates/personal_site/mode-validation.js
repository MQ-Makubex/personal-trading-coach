(() => {
  'use strict';

  const root = document.querySelector('[data-mode-validation-app]');
  const dataNode = document.getElementById('modeValidationData');
  if (!root || !dataNode) return;

  let projection;
  try {
    projection = JSON.parse(dataNode.textContent || '{}');
  } catch (_error) {
    projection = {modes: [], tasks: [], propositions: [], evidence: [], runs: [], reviews: []};
  }

  const modeSelect = document.getElementById('modeValidationMode');
  const taskSelect = document.getElementById('modeValidationTask');
  const feedback = document.querySelector('[data-mode-validation-feedback]');
  const surfaceLabel = document.querySelector('[data-mode-validation-surface]');
  const sessionLabel = document.querySelector('[data-mode-validation-session-state]');
  const panels = new Map(
    Array.from(document.querySelectorAll('[data-mode-validation-panel-body]')).map(node => [node.dataset.modeValidationPanelBody, node])
  );
  const tabs = Array.from(document.querySelectorAll('[data-mode-validation-tab]'));
  let sessionToken = null;
  let heartbeatTimer = null;
  let localWriteEnabled = false;
  let pendingRunPreview = null;
  let pendingModeChangePreview = null;
  let refreshTimer = null;

  const copy = {
    active: '活动中',
    superseded: '已替代',
    closed: '已关闭',
    draft: '草案',
    collecting: '收集证据',
    awaiting_review: '等待评审',
    supported: '支持',
    opposed: '反对',
    mixed: '证据混合',
    insufficient: '证据不足',
    continue_validating: '继续验证',
    replicable: '可复制',
    avoid: '回避',
    revise_new_version: '修订为新版本',
    formal: '正式验证',
    exploratory: '探索运行',
    awaiting_qualification: '等待样本资格',
    queued: '已排队',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
    invalidated: '已作废',
    pending: '待确认资格',
    included: '已纳入',
    excluded: '已排除',
    qualification_missing: '资格缺失',
    pass: '审计通过',
    pass_with_warning: '带警告通过',
    support: '支持',
    oppose: '反对',
    indeterminate: '无法判断'
  };

  function text(value, fallback = '待补充') {
    if (value === null || value === undefined || value === '') return fallback;
    return String(value);
  }

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = text(content, '');
    return element;
  }

  function empty(message) {
    return node('div', 'empty-state mode-validation-empty', message);
  }

  function badge(value, kind = '') {
    const element = node('span', `mode-validation-badge ${kind}`.trim(), copy[value] || value || '待核验');
    return element;
  }

  function actionButton(label, action, kind = '') {
    const button = node('button', `mode-validation-action ${kind}`.trim(), label);
    button.type = 'button';
    button.dataset.localWrite = '';
    button.addEventListener('click', action);
    return button;
  }

  async function api(path, payload = {}) {
    if (!sessionToken) throw new Error('本机会话不可用。');
    const response = await fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Workbench-Token': sessionToken},
      body: JSON.stringify(payload)
    });
    const result = await response.json().catch(() => ({}));
    if (response.status === 403) {
      sessionToken = null;
      localWriteEnabled = false;
      throw new Error('本机会话已失效，请刷新页面。');
    }
    if (!response.ok) throw new Error(result.message || '本机操作失败。');
    return result;
  }

  async function refreshProjection() {
    const response = await fetch('/api/mode-validation/snapshot', {cache: 'no-store'});
    if (!response.ok) throw new Error('无法刷新模式验证状态。');
    projection = await response.json();
    const modeId = modeSelect.value;
    const taskId = taskSelect.value;
    if (modeId && (projection.modes || []).some(item => item.id === modeId)) modeSelect.value = modeId;
    updateTaskOptions(taskId);
    renderRiskQueue();
    renderAll();
  }

  async function runAction(button, pendingLabel, operation) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = pendingLabel;
    setFeedback('正在写入本地验证库。');
    try {
      await operation();
      await refreshProjection();
      setFeedback('本地验证状态已更新。', 'success');
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : '本机操作失败。', 'error');
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function renderRiskQueue() {
    const risk = document.querySelector('.mode-validation-risk');
    if (!risk) return;
    const heading = risk.querySelector('.mode-validation-risk-heading > strong');
    const groups = new Map((projection.risk_queue || []).map(group => [group.kind, group]));
    let total = 0;
    risk.querySelectorAll('[data-risk-kind]').forEach(section => {
      const group = groups.get(section.dataset.riskKind) || {count: 0, items: []};
      total += Number(group.count || 0);
      const count = section.querySelector('header span');
      const list = section.querySelector('ul');
      if (count) count.textContent = String(group.count || 0);
      if (!list) return;
      list.replaceChildren();
      if (!(group.items || []).length) {
        list.append(node('li', 'mode-validation-risk-clear', '当前无此类事项'));
        return;
      }
      group.items.forEach(item => {
        const row = node('li');
        row.append(node('strong', '', item.label), node('small', 'mono', item.id));
        list.append(row);
      });
    });
    if (heading) heading.textContent = String(total);
  }

  function definitionList(rows) {
    const list = node('dl', 'mode-validation-definitions');
    rows.forEach(([label, value]) => {
      const group = node('div');
      group.append(node('dt', '', label), node('dd', '', value));
      list.append(group);
    });
    return list;
  }

  function selectedMode() {
    return (projection.modes || []).find(item => item.id === modeSelect.value) || null;
  }

  function selectedTask() {
    return (projection.tasks || []).find(item => item.task_id === taskSelect.value) || null;
  }

  function related(collection, taskId) {
    return (collection || []).filter(item => item.task_id === taskId);
  }

  function renderOverview() {
    const target = panels.get('overview');
    target.replaceChildren();
    const mode = selectedMode();
    const task = selectedTask();
    if (!mode) {
      target.append(empty('尚未建立结构化交易模式。'));
      return;
    }
    if (!task) {
      const state = empty('这个模式版本尚未建立验证任务。本机工作台连接后可以从模式定义生成任务和命题草案。');
      state.append(badge(mode.status || 'validating'));
      if (localWriteEnabled) {
        const create = actionButton('建立验证任务', event => {
          runAction(event.currentTarget, '正在建立', async () => {
            await api('/api/mode-validation/tasks', {mode_id: mode.id, mode_version: mode.version});
          });
        }, 'primary');
        state.append(create);
      }
      target.append(state);
      return;
    }
    const heading = node('header', 'mode-validation-section-heading');
    const title = node('div');
    title.append(node('span', 'page-context mono', task.task_id), node('h2', '', `${mode.name} v${mode.version}`));
    const state = node('div', 'mode-validation-heading-state');
    state.append(badge(task.status), task.mode_drift ? badge('模式定义已漂移', 'danger') : badge('模式快照一致', 'success'));
    heading.append(title, state);
    const goal = task.research_goal || {};
    target.append(
      heading,
      definitionList([
        ['研究目标', goal.goal || goal.objective || '验证当前模式版本是否值得继续积累证据'],
        ['模式快照', task.mode_snapshot_hash || '待核验'],
        ['允许路径', Array.isArray(goal.allowed_paths) ? goal.allowed_paths.join('、') : '历史回放、前向观察'],
        ['完成口径', goal.completion || '必需命题完成证据审计与人工评审']
      ])
    );
  }

  function renderPropositions() {
    const target = panels.get('propositions');
    target.replaceChildren();
    const task = selectedTask();
    if (!task) {
      target.append(empty('建立验证任务后，这里会显示从模式定义生成的命题草案。'));
      return;
    }
    const propositions = related(projection.propositions, task.task_id);
    if (!propositions.length) {
      target.append(empty('当前任务还没有命题草案。'));
      return;
    }
    const list = node('div', 'mode-validation-proposition-list');
    propositions.forEach(item => {
      const article = node('article', 'mode-validation-proposition');
      const heading = node('header');
      const title = node('div');
      title.append(node('h3', '', item.title), node('small', 'mono', item.proposition_id));
      heading.append(title, badge(item.workflow_status));
      const criteria = Array.isArray(item.acceptance_criteria) ? item.acceptance_criteria : [];
      const falsifiers = Array.isArray(item.falsifiers) ? item.falsifiers : [];
      article.append(
        heading,
        node('p', '', item.statement),
        definitionList([
          ['验收标准', criteria.map(rule => `${rule.metric || '指标'} ${rule.operator || ''} ${text(rule.value, '')}`).join('；') || '待补充'],
          ['证伪条件', falsifiers.map(rule => `${rule.metric || '指标'} ${rule.operator || ''} ${text(rule.value, '')}`).join('；') || '待补充']
        ])
      );
      if (localWriteEnabled && item.workflow_status === 'draft') {
        const actions = node('div', 'mode-validation-inline-actions');
        actions.append(actionButton('确认命题', event => {
          runAction(event.currentTarget, '正在确认', async () => {
            await api(`/api/mode-validation/propositions/${encodeURIComponent(item.proposition_id)}/confirm`);
          });
        }, 'primary'));
        article.append(actions);
      }
      list.append(article);
    });
    target.append(list);
  }

  function renderEvidence() {
    const target = panels.get('evidence');
    target.replaceChildren();
    const task = selectedTask();
    if (!task) {
      target.append(empty('选择验证任务后查看通过发布审计的证据。'));
      return;
    }
    const propositionIds = new Set(related(projection.propositions, task.task_id).map(item => item.proposition_id));
    const evidenceRows = (projection.evidence || []).filter(item => propositionIds.has(item.proposition_id));
    if (!evidenceRows.length) {
      target.append(empty('当前任务还没有可发布证据。审计失败的证据不会出现在这里。'));
      return;
    }
    const list = node('div', 'mode-validation-evidence-list');
    evidenceRows.forEach(item => {
      const article = node('article', 'mode-validation-evidence');
      const heading = node('header');
      const title = node('div');
      title.append(node('h3', '', item.summary), node('small', 'mono', item.evidence_id));
      heading.append(title, badge(item.audit_outcome, item.audit_outcome === 'pass' ? 'success' : 'warning'));
      const sources = Array.isArray(item.source_refs) ? item.source_refs.join('、') : '待核验';
      article.append(
        heading,
        definitionList([
          ['证据方向', copy[item.direction] || item.direction],
          ['独立证据段', item.independent_segment ? '是' : '否'],
          ['满足必需标准', item.satisfies_required_criterion ? '可以' : '不能单独满足'],
          ['来源', sources]
        ])
      );
      list.append(article);
    });
    target.append(list);
  }

  function renderRuns() {
    const target = panels.get('runs');
    target.replaceChildren();
    const task = selectedTask();
    if (!task) {
      target.append(empty('选择验证任务后查看运行卡。'));
      return;
    }
    const runs = related(projection.runs, task.task_id);
    if (localWriteEnabled) target.append(renderRunComposer(task));
    if (!runs.length) {
      target.append(empty('当前任务尚未创建验证运行。'));
      return;
    }
    const wrap = node('div', 'table-scroll mode-validation-table-scroll');
    const table = node('table');
    const head = node('thead');
    const headingRow = node('tr');
    ['运行标识', '验证器', '类型', '状态', '协议哈希', '创建时间'].forEach(label => headingRow.append(node('th', '', label)));
    head.append(headingRow);
    const body = node('tbody');
    runs.forEach(item => {
      const row = node('tr');
      row.append(
        node('td', 'mono', item.run_id),
        node('td', '', item.validator_id),
        node('td', '', copy[item.run_kind] || item.run_kind),
        node('td', '', copy[item.status] || item.status),
        node('td', 'mono', item.protocol_hash),
        node('td', 'mono', item.created_at)
      );
      body.append(row);
    });
    table.append(head, body);
    wrap.append(table);
    target.append(wrap);
    const candidates = (projection.candidates || []).filter(candidate => runs.some(run => run.run_id === candidate.run_id));
    runs.forEach(run => {
      const runCandidates = candidates.filter(candidate => candidate.run_id === run.run_id);
      const section = node('section', 'mode-validation-run-detail');
      const heading = node('header');
      const title = node('div');
      title.append(node('h3', '', copy[run.status] || run.status), node('small', 'mono', run.run_id));
      heading.append(title, badge(run.run_kind));
      section.append(heading);
      if (runCandidates.length) {
        const list = node('div', 'mode-validation-candidate-list');
        runCandidates.forEach(candidate => list.append(renderCandidate(run, candidate)));
        section.append(list);
      }
      if (localWriteEnabled) {
        const pending = runCandidates.some(candidate => candidate.qualification === 'pending');
        const actions = node('div', 'mode-validation-inline-actions');
        if (run.status === 'awaiting_qualification' && !pending) {
          actions.append(actionButton('加入执行队列', event => {
            runAction(event.currentTarget, '正在排队', async () => {
              await api(`/api/mode-validation/runs/${encodeURIComponent(run.run_id)}/execute`);
              startRefreshPolling();
            });
          }, 'primary'));
        }
        if (['awaiting_qualification', 'queued', 'running', 'succeeded'].includes(run.status)) {
          actions.append(actionButton(run.status === 'running' ? '请求安全停止' : '作废运行', event => {
            if (run.status === 'running' || run.status === 'queued') {
              runAction(event.currentTarget, '正在处理', async () => {
                await api(`/api/mode-validation/runs/${encodeURIComponent(run.run_id)}/cancel`);
              });
              return;
            }
            const reason = window.prompt('请说明作废原因。', '样本或输入需要重新核验');
            if (!reason) return;
            runAction(event.currentTarget, '正在作废', async () => {
              await api(`/api/mode-validation/runs/${encodeURIComponent(run.run_id)}/invalidate`, {reason});
            });
          }));
        }
        if (actions.childElementCount) section.append(actions);
      }
      target.append(section);
    });
  }

  function formField(label, input) {
    const wrapper = node('label', 'mode-validation-form-field');
    wrapper.append(node('span', '', label), input);
    return wrapper;
  }

  function renderRunComposer(task) {
    const form = node('form', 'mode-validation-composer');
    form.dataset.localWrite = '';
    const heading = node('header');
    heading.append(node('h3', '', '新建验证运行'), node('p', '', '先生成预览，再冻结协议并创建新运行标识。'));
    const grid = node('div', 'mode-validation-form-grid');
    const propositionSelect = node('select');
    propositionSelect.name = 'proposition_id';
    related(projection.propositions, task.task_id)
      .filter(item => item.workflow_status !== 'draft' && item.workflow_status !== 'superseded')
      .forEach(item => {
        const option = node('option', '', item.title);
        option.value = item.proposition_id;
        propositionSelect.append(option);
      });
    const validatorSelect = node('select');
    validatorSelect.name = 'validator_id';
    (projection.validators || []).forEach(item => {
      const option = node('option', '', item.name);
      option.value = item.id;
      validatorSelect.append(option);
    });
    const kindSelect = node('select');
    kindSelect.name = 'run_kind';
    [['formal', '正式验证'], ['exploratory', '探索运行']].forEach(([value, label]) => {
      const option = node('option', '', label);
      option.value = value;
      kindSelect.append(option);
    });
    const today = new Date().toISOString().slice(0, 10);
    const oneYearAgo = `${Number(today.slice(0, 4)) - 1}${today.slice(4)}`;
    const dateFrom = node('input');
    dateFrom.type = 'date';
    dateFrom.name = 'date_from';
    dateFrom.value = oneYearAgo;
    const dateTo = node('input');
    dateTo.type = 'date';
    dateTo.name = 'date_to';
    dateTo.value = today;
    grid.append(
      formField('模式命题', propositionSelect),
      formField('注册验证器', validatorSelect),
      formField('运行类型', kindSelect),
      formField('开始日期', dateFrom),
      formField('结束日期', dateTo)
    );
    const actions = node('div', 'mode-validation-inline-actions');
    const previewButton = node('button', 'mode-validation-action primary', '生成运行预览');
    previewButton.type = 'submit';
    actions.append(previewButton);
    const previewTarget = node('div', 'mode-validation-run-preview');
    form.append(heading, grid, actions, previewTarget);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      previewButton.disabled = true;
      previewButton.textContent = '正在预览';
      previewTarget.replaceChildren();
      try {
        const validator = validatorSelect.value;
        const parameters = validator === 'historical-cycle-replay'
          ? {
              date_from: dateFrom.value, date_to: dateTo.value,
              inclusion_rules: ['完整交易周期且符合命题样本口径'],
              exclusion_rules: ['缺少当时证据或无法确认模式资格'],
              control_definition: '同一时间范围内的全部完整交易周期'
            }
          : {
              window_start: dateFrom.value, window_end: dateTo.value,
              event_timing: 'after_close',
              qualification_deadline: {anchor: 'next_open', lead_minutes: 0},
              inclusion_rules: ['观察窗口内的全部新决策事件'],
              exclusion_rules: ['仅按当时信息确认不符合模式资格']
            };
        pendingRunPreview = await api('/api/mode-validation/runs/preview', {
          task_id: task.task_id,
          proposition_id: propositionSelect.value,
          validator_id: validator,
          run_kind: kindSelect.value,
          parameters
        });
        previewTarget.append(
          node('strong', '', '运行预览已冻结'),
          definitionList([
            ['验证器', pendingRunPreview.validator_id],
            ['候选样本', `${(pendingRunPreview.candidates || []).length} 项`],
            ['协议哈希', pendingRunPreview.protocol_hash],
            ['模式快照', pendingRunPreview.mode_snapshot_hash]
          ])
        );
        previewTarget.append(actionButton('确认创建运行', buttonEvent => {
          runAction(buttonEvent.currentTarget, '正在创建', async () => {
            await api('/api/mode-validation/runs', {preview_id: pendingRunPreview.preview_id});
            pendingRunPreview = null;
          });
        }, 'primary'));
      } catch (error) {
        previewTarget.append(node('div', 'mode-validation-inline-error', error instanceof Error ? error.message : '无法生成预览。'));
      } finally {
        previewButton.disabled = false;
        previewButton.textContent = '生成运行预览';
      }
    });
    if (!propositionSelect.options.length) {
      form.classList.add('is-disabled');
      Array.from(form.elements).forEach(element => { element.disabled = true; });
      form.append(node('div', 'mode-validation-inline-error', '至少确认一个命题后才能创建运行。'));
    }
    validatorSelect.addEventListener('change', () => {
      if (validatorSelect.value === 'forward-decision-observation') kindSelect.value = 'formal';
      kindSelect.disabled = validatorSelect.value === 'forward-decision-observation';
    });
    return form;
  }

  function renderCandidate(run, candidate) {
    const row = node('article', 'mode-validation-candidate');
    const context = candidate.masked_context || {};
    const heading = node('header');
    const title = node('div');
    title.append(
      node('strong', '', context.title || context.stock_name || context.stock_code || '验证候选'),
      node('small', 'mono', candidate.source_ref)
    );
    heading.append(title, badge(candidate.qualification));
    row.append(heading, definitionList([
      ['观察时间', candidate.observed_at],
      ['资格截止', candidate.qualification_deadline || '冻结前人工确认'],
      ['独立证据段', context.independent_segment ? '是' : '否']
    ]));
    if (localWriteEnabled && ['pending', 'qualification_missing'].includes(candidate.qualification)) {
      const late = candidate.qualification === 'qualification_missing';
      const reason = node('input');
      reason.type = 'text';
      reason.placeholder = late ? '逾期补录必须说明当时依据' : '排除时必须填写原因';
      reason.setAttribute('aria-label', '资格判断原因');
      const actions = node('div', 'mode-validation-candidate-actions');
      actions.append(
        reason,
        actionButton(late ? '逾期补录纳入' : '纳入', event => {
          if (late && !reason.value.trim()) {
            setFeedback('逾期补录必须说明当时可见的依据。', 'error');
            reason.focus();
            return;
          }
          runAction(event.currentTarget, '正在记录', async () => {
            await api(`/api/mode-validation/runs/${encodeURIComponent(run.run_id)}/candidates/${encodeURIComponent(candidate.candidate_id)}/qualify`, {qualification: 'included', reason: reason.value.trim()});
          });
        }, 'primary'),
        actionButton(late ? '逾期补录排除' : '排除', event => {
          if (!reason.value.trim()) {
            setFeedback('排除候选必须填写当时可见的原因。', 'error');
            reason.focus();
            return;
          }
          runAction(event.currentTarget, '正在记录', async () => {
            await api(`/api/mode-validation/runs/${encodeURIComponent(run.run_id)}/candidates/${encodeURIComponent(candidate.candidate_id)}/qualify`, {qualification: 'excluded', reason: reason.value.trim()});
          });
        })
      );
      row.append(actions);
    }
    return row;
  }

  function renderReviews() {
    const target = panels.get('reviews');
    target.replaceChildren();
    const task = selectedTask();
    if (!task) {
      target.append(empty('选择验证任务后查看不可变评审历史。'));
      return;
    }
    const reviews = related(projection.reviews, task.task_id);
    if (localWriteEnabled) {
      target.append(renderReviewComposer(task));
      const modeComposer = renderModeReviewComposer(task);
      if (modeComposer) target.append(modeComposer);
    }
    if (!reviews.length) {
      target.append(empty('当前任务还没有人工评审事件。'));
      return;
    }
    const list = node('ol', 'mode-validation-review-list');
    reviews.forEach(item => {
      const row = node('li');
      const heading = node('header');
      const title = node('div');
      title.append(node('strong', '', item.scope === 'mode' ? '模式整体评审' : '命题评审'), node('small', 'mono', item.created_at));
      heading.append(title, badge(item.verdict, item.needs_rereview ? 'danger' : ''));
      row.append(heading, node('p', '', item.note));
      if (item.needs_rereview) row.append(node('strong', 'mode-validation-warning-text', '引用证据已失效，需要重新评审。'));
      list.append(row);
    });
    target.append(list);
  }

  function renderReviewComposer(task) {
    const form = node('form', 'mode-validation-composer');
    form.dataset.localWrite = '';
    const heading = node('header');
    heading.append(node('h3', '', '追加命题评审'), node('p', '', '新结论会引用当前可见证据，并保留此前评审。'));
    const grid = node('div', 'mode-validation-form-grid');
    const propositionSelect = node('select');
    propositionSelect.name = 'proposition_id';
    related(projection.propositions, task.task_id)
      .filter(item => item.workflow_status !== 'draft' && item.workflow_status !== 'superseded')
      .forEach(item => {
        const option = node('option', '', item.title);
        option.value = item.proposition_id;
        propositionSelect.append(option);
      });
    const verdictSelect = node('select');
    [['supported', '支持'], ['opposed', '反对'], ['mixed', '证据混合'], ['insufficient', '证据不足']].forEach(([value, label]) => {
      const option = node('option', '', label);
      option.value = value;
      verdictSelect.append(option);
    });
    const note = node('textarea');
    note.rows = 3;
    note.placeholder = '说明结论、反向证据和限制';
    grid.append(
      formField('模式命题', propositionSelect),
      formField('人工结论', verdictSelect),
      formField('评审说明', note)
    );
    const submit = node('button', 'mode-validation-action primary', '追加评审事件');
    submit.type = 'submit';
    form.append(heading, grid, submit);
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!note.value.trim()) {
        setFeedback('评审说明不能为空。', 'error');
        note.focus();
        return;
      }
      const evidenceIds = (projection.evidence || [])
        .filter(item => item.proposition_id === propositionSelect.value)
        .map(item => item.evidence_id);
      runAction(submit, '正在追加', async () => {
        await api('/api/mode-validation/reviews', {
          task_id: task.task_id,
          scope: 'proposition',
          verdict: verdictSelect.value,
          note: note.value.trim(),
          proposition_id: propositionSelect.value,
          evidence_ids: evidenceIds
        });
      });
    });
    if (!propositionSelect.options.length) {
      form.classList.add('is-disabled');
      Array.from(form.elements).forEach(element => { element.disabled = true; });
      form.append(node('div', 'mode-validation-inline-error', '至少确认一个命题后才能评审。'));
    }
    return form;
  }

  function renderModeReviewComposer(task) {
    const propositions = related(projection.propositions, task.task_id).filter(item => item.required && item.workflow_status !== 'superseded');
    const currentReviewed = new Set(
      related(projection.reviews, task.task_id)
        .filter(item => item.scope === 'proposition' && item.is_current && !item.needs_rereview)
        .map(item => item.proposition_id)
    );
    if (!propositions.length || propositions.some(item => !currentReviewed.has(item.proposition_id))) return null;
    const form = node('form', 'mode-validation-composer mode-validation-mode-review');
    form.dataset.localWrite = '';
    const heading = node('header');
    heading.append(node('h3', '', '模式整体人工评审'), node('p', '', '系统只汇总证据，模式去留由你单独决定。'));
    const grid = node('div', 'mode-validation-form-grid');
    const verdict = node('select');
    [
      ['continue_validating', '继续验证'],
      ['replicable', '可复制'],
      ['avoid', '回避'],
      ['revise_new_version', '修订为新版本']
    ].forEach(([value, label]) => {
      const option = node('option', '', label);
      option.value = value;
      verdict.append(option);
    });
    const note = node('textarea');
    note.rows = 3;
    note.placeholder = '说明模式级决定、反向证据和剩余限制';
    grid.append(formField('整体决定', verdict), formField('评审说明', note));
    const submit = node('button', 'mode-validation-action primary', '记录整体评审');
    submit.type = 'submit';
    form.append(heading, grid, submit);
    if (pendingModeChangePreview && pendingModeChangePreview.task_id === task.task_id) {
      const preview = node('section', 'mode-validation-mode-change-preview');
      preview.append(
        node('strong', '', '请第二次确认模式定义文件变更'),
        definitionList([
          ['当前状态', pendingModeChangePreview.before.status],
          ['目标状态', pendingModeChangePreview.after.status],
          ['写入前哈希', pendingModeChangePreview.pre_write_hash]
        ])
      );
      const comparison = node('div', 'mode-validation-mode-change-comparison');
      [
        ['写入前完整定义', pendingModeChangePreview.before],
        ['写入后完整定义', pendingModeChangePreview.after]
      ].forEach(([label, value]) => {
        const column = node('section');
        column.append(
          node('span', '', label),
          node('pre', 'mono', JSON.stringify(value, null, 2))
        );
        comparison.append(column);
      });
      preview.append(comparison);
      preview.append(actionButton('确认写入模式状态', event => {
        runAction(event.currentTarget, '正在写入', async () => {
          await api('/api/mode-validation/mode-change/confirm', {
            preview_id: pendingModeChangePreview.preview_id,
            pre_write_hash: pendingModeChangePreview.pre_write_hash
          });
          pendingModeChangePreview = null;
        });
      }, 'primary'));
      form.append(preview);
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!note.value.trim()) {
        setFeedback('模式整体评审说明不能为空。', 'error');
        note.focus();
        return;
      }
      submit.disabled = true;
      submit.textContent = '正在记录';
      try {
        const review = await api('/api/mode-validation/reviews', {
          task_id: task.task_id,
          scope: 'mode',
          verdict: verdict.value,
          note: note.value.trim(),
          proposition_id: null,
          evidence_ids: []
        });
        if (verdict.value !== 'revise_new_version') {
          const targetStatus = verdict.value === 'continue_validating' ? 'validating' : verdict.value;
          pendingModeChangePreview = await api('/api/mode-validation/mode-change/preview', {
            task_id: task.task_id,
            review_event_id: review.review_event_id,
            target_status: targetStatus
          });
        }
        await refreshProjection();
        setFeedback(verdict.value === 'revise_new_version' ? '已记录建立新版本的决定。' : '整体评审已记录，请检查变更预览并再次确认。', 'success');
      } catch (error) {
        setFeedback(error instanceof Error ? error.message : '模式整体评审失败。', 'error');
      } finally {
        submit.disabled = false;
        submit.textContent = '记录整体评审';
      }
    });
    return form;
  }

  function renderAll() {
    renderOverview();
    renderPropositions();
    renderEvidence();
    renderRuns();
    renderReviews();
  }

  function updateTaskOptions(preferredTask = '') {
    const modeId = modeSelect.value;
    const tasks = (projection.tasks || []).filter(item => item.mode_id === modeId);
    taskSelect.replaceChildren();
    if (!tasks.length) {
      const option = node('option', '', '尚未建立验证任务');
      option.value = '';
      taskSelect.append(option);
      return;
    }
    tasks.forEach(item => {
      const option = node('option', '', `${copy[item.status] || item.status} · ${text(item.created_at)}`);
      option.value = item.task_id;
      taskSelect.append(option);
    });
    const preferred = tasks.find(item => item.task_id === preferredTask) || tasks.find(item => item.status === 'active') || tasks[0];
    taskSelect.value = preferred.task_id;
  }

  function syncUrl() {
    const params = new URLSearchParams(location.search);
    if (modeSelect.value) params.set('mode', modeSelect.value); else params.delete('mode');
    if (taskSelect.value) params.set('task', taskSelect.value); else params.delete('task');
    const activeTab = tabs.find(tab => tab.getAttribute('aria-selected') === 'true');
    if (activeTab) params.set('tab', activeTab.dataset.modeValidationTab);
    history.replaceState(null, '', `${location.pathname}${params.toString() ? `?${params}` : ''}`);
  }

  function activateTab(tab, focus = false) {
    tabs.forEach(item => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      const panel = document.querySelector(`[data-mode-validation-panel="${item.dataset.modeValidationTab}"]`);
      if (panel) panel.hidden = !selected;
    });
    if (focus) tab.focus();
    syncUrl();
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
      if (event.key === 'Home') nextIndex = 0;
      if (event.key === 'End') nextIndex = tabs.length - 1;
      activateTab(tabs[nextIndex], true);
    });
  });

  modeSelect.addEventListener('change', () => {
    updateTaskOptions();
    renderAll();
    syncUrl();
  });
  taskSelect.addEventListener('change', () => {
    renderAll();
    syncUrl();
  });

  function setFeedback(message, kind = '') {
    feedback.textContent = message || '';
    feedback.dataset.kind = kind;
  }

  function startRefreshPolling() {
    if (refreshTimer) return;
    refreshTimer = window.setInterval(async () => {
      try {
        await refreshProjection();
        const active = (projection.runs || []).some(run => ['queued', 'running'].includes(run.status));
        if (!active) {
          window.clearInterval(refreshTimer);
          refreshTimer = null;
        }
      } catch (_error) {
        window.clearInterval(refreshTimer);
        refreshTimer = null;
      }
    }, 1200);
  }

  async function openLocalSession() {
    if (!['127.0.0.1', '::1', 'localhost'].includes(location.hostname)) return;
    try {
      const response = await fetch('/api/mode-validation/session', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}'
      });
      if (!response.ok) return;
      const payload = await response.json();
      if (!payload.token) return;
      sessionToken = payload.token;
      localWriteEnabled = true;
      surfaceLabel.textContent = '本机可写';
      sessionLabel.textContent = '写入会话只保存在当前页面内存';
      setFeedback('本机工作台已连接。', 'success');
      await refreshProjection();
      if ((projection.runs || []).some(run => ['queued', 'running'].includes(run.status))) startRefreshPolling();
      heartbeatTimer = window.setInterval(async () => {
        if (!sessionToken) return;
        const heartbeat = await fetch('/api/mode-validation/session/heartbeat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-Workbench-Token': sessionToken},
          body: '{}'
        });
        if (heartbeat.status === 403) {
          sessionToken = null;
          localWriteEnabled = false;
          window.clearInterval(heartbeatTimer);
          surfaceLabel.textContent = '线上只读';
          sessionLabel.textContent = '本机会话已失效，请刷新页面';
          setFeedback('本机会话已失效，写入已关闭。', 'error');
          renderAll();
        }
      }, 15000);
    } catch (_error) {
      sessionToken = null;
    }
  }

  window.addEventListener('pagehide', () => {
    if (!sessionToken) return;
    fetch('/api/mode-validation/session/close', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Workbench-Token': sessionToken},
      body: '{}',
      keepalive: true
    }).catch(() => {});
    sessionToken = null;
    localWriteEnabled = false;
  });

  const params = new URLSearchParams(location.search);
  const requestedMode = params.get('mode');
  if (requestedMode && (projection.modes || []).some(item => item.id === requestedMode)) modeSelect.value = requestedMode;
  updateTaskOptions(params.get('task') || root.dataset.selectedTask || '');
  const requestedTab = params.get('tab');
  const initialTab = tabs.find(tab => tab.dataset.modeValidationTab === requestedTab) || tabs[0];
  activateTab(initialTab);
  renderAll();
  openLocalSession();
})();
