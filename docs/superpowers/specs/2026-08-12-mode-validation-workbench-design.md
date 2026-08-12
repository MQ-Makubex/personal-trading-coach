# 模式验证工作台 v1 设计规格

## 目标

在不改变现有页面内容和布局的前提下，新增一个独立的“模式验证”页面，把当前已有的个人交易模式变成可持续验证的研究对象。第一版优先完成从任务建立、命题确认、样本协议冻结、验证运行、证据审计到人工评审的闭环，不做实时荐股、不自动生成新模式，也不引入 Vibe-Trading 运行时。

## 已批准边界

- 现有首页、时间线、股票故事、交易模式、导师视角、交易底账和纪律规则保持原样，只在共享导航新增“模式验证”。
- 本机工作台可写，Cloudflare 静态部署只读。两者使用同一信息结构。
- 只实现两个注册验证器：`historical-cycle-replay` 和 `forward-decision-observation`。
- 确定性回测只保留注册接口，不在 v1 启用。
- 不实现交易日志行为诊断、候选模式挖掘、Shadow Account 或实时交易建议。
- 不直接依赖 Vibe-Trading、MCP、LLM 运行时或第三方前端包。

## 设计判断

这是面向单一用户的高密度私人研究工作台，并且是对现有站点的保留式新增。沿用现站的深色主题、系统字体、蓝色主强调、语义风险色、6px 圆角和原生 HTML/CSS/JavaScript。设计参数为 `DESIGN_VARIANCE: 3`、`MOTION_INTENSITY: 2`、`VISUAL_DENSITY: 8`。动效只用于按钮反馈和状态切换，页面优先显示风险与阻塞，不使用营销页视觉、插图或装饰动画。

## 信息架构

页面从上到下固定为四层：

1. 运行表面提示：本机可写或线上只读、服务会话状态、最近刷新时间。
2. 验证风险队列：按依赖已作废、审计失败、需要重新评审、等待首次评审、收集证据排序。
3. 上下文选择器：模式、版本、验证任务。一个模式版本同时只允许一个活动任务。
4. 五个页签：任务概览、模式命题、研究证据、验证运行、评审历史。

桌面端使用 300px 左侧风险队列和右侧主工作区。小于 768px 时变为单列，风险队列在主内容之前，上下文选择器和页签允许横向滚动。所有表格必须置于可横向滚动容器。页面必须具有加载、空、错误、只读、写入中和写入失败状态。

## 运行边界

### 静态投影

`scripts/build_personal_site.py` 从 `state/trading_modes.json`、`state/mode_validation.sqlite` 和经过审计的运行索引生成脱敏投影。投影嵌入 `mode-validation.html`，也写入 `site_data.json`。静态投影不包含原始日志、绝对路径、令牌、失败审计证据正文、未审计运行产物或研究数据库连接信息。

### 本地工作台服务

`scripts/mode_validation_service.py` 先生成静态站，再通过 `ThreadingHTTPServer` 仅监听 `127.0.0.1`。它提供同一个 `mode-validation.html` 和 `/api/mode-validation/*` 接口。

- 浏览器通过 `POST /api/mode-validation/session` 建立会话，服务返回随机令牌。
- 令牌只保存在服务内存和页面 JavaScript 闭包中，不写入静态文件、URL、Cookie、`localStorage` 或 `sessionStorage`。
- 每次写请求必须带 `X-Workbench-Token`，并具有与当前 `127.0.0.1:<port>` 完全一致的 `Origin`。
- 页面每 15 秒发送一次心跳，45 秒无心跳后令牌失效。`pagehide` 会调用关闭接口。停止服务会立即清空令牌。
- 非回环 Host、非回环 Origin、缺失令牌、错误令牌和过期令牌都返回 403。
- GET 投影可以只读访问，所有写入只由本地接口完成。

## 存储模型

`state/account_ledger.sqlite` 继续只保存交易事实，`state/trading_modes.json` 继续只保存模式定义、版本和模式整体状态。新库 `state/mode_validation.sqlite` 使用 WAL 和外键，包含以下表：

### `validation_tasks`

- `task_id`、`mode_id`、`mode_version`
- `status`: `active`、`superseded`、`closed`
- `mode_snapshot_json`、`mode_snapshot_hash`
- `research_goal_json`
- `created_at`、`superseded_by_task_id`

数据库唯一索引保证同一 `mode_id + mode_version` 最多一个 `active` 任务。建立新任务时旧任务改为 `superseded`，其数据不删除。

### `propositions`

- `proposition_id`、`task_id`、`title`、`statement`
- `acceptance_criteria_json`、`falsifiers_json`
- `workflow_status`: `draft`、`collecting`、`awaiting_review`、`closed`、`superseded`
- `required`、`confirmed_at`、`created_at`

草案可以由模式环境、触发、边界和失效字段生成。只有具有至少一个可执行证伪条件的命题才能确认。

### `validation_runs`

- `run_id`、`task_id`、`proposition_id`、`validator_id`
- `run_kind`: `exploratory`、`formal`
- `status`: `awaiting_qualification`、`queued`、`running`、`succeeded`、`failed`、`cancelled`、`invalidated`
- `mode_snapshot_hash`、`protocol_json`、`protocol_hash`
- `config_json`、`data_fingerprint`、`result_json`
- `artifact_relative_path`、`artifact_hash`
- `warning_json`、`failure_reason`、`created_at`、`started_at`、`finished_at`

运行卡不可变字段建立后不允许更新。状态只能按合法状态机推进。失败、取消、中断和作废都是终态，重试必须创建新 `run_id`。

### `run_candidates`

- `candidate_id`、`run_id`、`source_ref`、`observed_at`
- `masked_context_json`
- `qualification`: `pending`、`included`、`excluded`、`qualification_missing`
- `qualification_reason`、`qualification_deadline`、`qualified_at`
- `outcome_json`、`outcome_revealed_at`

历史回放在所有候选完成资格判断前不得写入或投影 `outcome_json`。前向观察逾期候选自动变为 `qualification_missing`，后续结果不能改变资格。

### `evidence`

- `evidence_id`、`run_id`、`proposition_id`
- `direction`: `support`、`oppose`、`indeterminate`
- `summary`、`metrics_json`、`source_refs_json`
- `independent_segment`、`created_at`

### `publication_audits`

- `audit_id`、`evidence_id`
- `outcome`: `pass`、`pass_with_warning`、`fail`
- `reasons_json`、`audited_at`

### `review_events`

- `review_event_id`、`task_id`、`proposition_id` 可空
- `scope`: `proposition`、`mode`
- `verdict`: 命题使用 `supported`、`opposed`、`mixed`、`insufficient`；模式使用 `continue_validating`、`replicable`、`avoid`、`revise_new_version`
- `note`、`evidence_ids_json`、`supersedes_event_id`、`created_at`

评审事件只追加。当前结论由最新的未被后续事件取代的记录投影。依赖作废时只产生 `needs_rereview` 投影，不改写历史评审。

## 模式快照与漂移

任务创建时把模式对象按 JSON 键排序、UTF-8、无多余空白序列化后计算 SHA-256。每次正式运行和写入评审前重新计算当前模式哈希。若同一版本内容漂移，工作台显示阻塞项并拒绝新的正式证据。修复方式只能是恢复定义或创建新版本和新任务。

## 研究目标和命题草案

任务研究目标固定包含：要验证的模式版本、必需命题、允许的验证路径、证据独立性要求、完成条件和明确的非目标。系统从模式定义产生四类可编辑草案：适用环境、触发有效性、执行边界、失效条件。用户必须填写或确认可观察验收标准和可执行证伪条件，才能把草案提升为 `collecting`。

## 注册验证器

验证器注册表是只读 Python 映射，条目包含稳定 id、中文名称、版本、允许的运行类型、固定参数字段和执行函数。API 只接受注册表内的 id 和已声明参数，额外字段直接拒绝。

### 历史交易周期回放

输入为模式任务、命题、日期范围和冻结的纳入排除规则。验证器从交易底账取得完整周期，从模式现有样本中标记已参与命题形成的案例。预览只展示股票、周期标识、首次动作日期和当时可得的决策引用，不展示最终盈亏、退出结果或事后说明。用户逐个纳入或排除并记录原因，冻结后才执行结果揭示和证据计算。无法证明盲化或缺少独立案例时审计最高为 `pass_with_warning`。

### 前向决策观察

输入为模式任务、命题、观察窗口、事件形成类型和资格截止规则。观察器扫描 `state/decision_events.md` 中命题确认后出现的结构化日期标题，为窗口内所有事件建立候选。日线收盘后候选默认在下一交易日开盘前完成资格，盘中候选默认在当日收盘前完成。正式观察开始前可以收紧截止时间，首个候选登记后不得延长。到期未判断的候选保留为 `qualification_missing`；逾期补录只形成警告，后续盈亏不能改变资格。

## 单执行队列

所有确认后的运行写入同一个持久队列。一个后台工作线程每次只执行一个 `queued` 运行。排队中可以取消；运行中只接受安全停止请求，验证器在阶段边界检查停止标记。服务启动时发现 `running` 状态即标记为 `failed`，原因是服务中断，不自动重试。

## 证据发布审计

审计按失败优先执行：

- `fail`: 运行已作废、任务或模式哈希不匹配、来源缺失、未绑定命题、命题缺失证伪条件、指标含 NaN 或 Infinity、探索运行冒充正式证据、产物哈希不匹配。
- `pass_with_warning`: 缺少独立证据段、历史案例不能盲化、前向资格存在逾期、样本或来源限制。
- `pass`: 无失败项和警告项。

只有 `pass` 与 `pass_with_warning` 进入静态投影。只有 `pass` 能单独满足必需标准。失败证据只在本机风险队列显示摘要，不发布正文。

## 人工评审和模式写入

命题评审必须引用当时可见的证据 id，并追加新事件。若引用证据后来作废，投影把命题标为需要重新评审但保留原事件。所有必需命题具有当前人工结论后，才允许模式整体评审。

模式整体评审先记录事件，不立即修改 `trading_modes.json`。若选择 `replicable`、`avoid` 或 `continue_validating`，工作台生成精确 JSON 前后差异和当前文件 SHA-256；用户第二次确认时必须回传预览 id 和哈希。哈希一致才使用同目录临时文件、`fsync` 和原子替换写入。写入失败保留原文件并返回错误。`revise_new_version` 只记录决定并提示建立新版本，不自动改写模式定义。

## API

只读：

- `GET /api/mode-validation/snapshot`
- `GET /api/mode-validation/validators`

会话：

- `POST /api/mode-validation/session`
- `POST /api/mode-validation/session/heartbeat`
- `POST /api/mode-validation/session/close`

写入：

- `POST /api/mode-validation/tasks`
- `POST /api/mode-validation/propositions/{id}/confirm`
- `POST /api/mode-validation/runs/preview`
- `POST /api/mode-validation/runs`
- `POST /api/mode-validation/runs/{id}/candidates/{id}/qualify`
- `POST /api/mode-validation/runs/{id}/execute`
- `POST /api/mode-validation/runs/{id}/cancel`
- `POST /api/mode-validation/runs/{id}/invalidate`
- `POST /api/mode-validation/reviews`
- `POST /api/mode-validation/mode-change/preview`
- `POST /api/mode-validation/mode-change/confirm`

所有 JSON 请求限制为 256 KiB，未知字段和非法枚举返回 400；并发写入使用一个进程锁和短事务。错误响应只包含稳定错误码和可读说明，不返回堆栈或绝对路径。

## 验收标准

- 构建产物新增 `mode-validation.html` 和 `assets/mode-validation.js`，所有原页面只多一个导航链接。
- 没有验证库时显示可理解的空态，并列出可建立任务的现有模式。
- 能在本机建立任务、确认含证伪条件的命题、预览并创建注册运行、完成候选资格、执行、审计和追加人工评审。
- 线上打开同一页面能看到脱敏投影，但看不到写控件或写 API。
- 非回环 Origin、错误或过期令牌的写入被拒绝。
- 同版本活动任务唯一、运行卡不可变、评审只追加、漂移阻塞、失败证据不发布均有自动化测试。
- 页面在 1440x1080 与 390x844 下无水平页面溢出，键盘可操作，焦点可见，移动端风险队列先于工作区。
- 完整 Python 测试、Node 测试、站点构建、隐私检查和 Playwright QA 全部通过。

## 后续版本

后续再讨论把模式验证工作台扩展为“私人交易教练台 + 复盘工作台”的统一产品。候选能力包括交易日志行为诊断、候选模式线索、规则回测、批量证据包和更深的复盘联动，但这些能力必须复用本版建立的任务、命题、运行卡、审计和人工评审边界。
