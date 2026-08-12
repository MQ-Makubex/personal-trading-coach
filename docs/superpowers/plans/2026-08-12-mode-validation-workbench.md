# 模式验证工作台 v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个线上只读、本机可写的模式验证页面，完成任务、命题、注册验证器、证据审计和人工评审的第一版闭环。

**Architecture:** 使用独立 SQLite 状态库和不可变运行产物保存验证事实，通过纯函数投影向静态站发布脱敏数据。本地 `ThreadingHTTPServer` 在同一静态页面上增加回环限定、内存令牌保护的写 API；线上构建没有写服务。

**Tech Stack:** Python 3 标准库、SQLite、现有静态 HTML/CSS/JavaScript 构建器、`unittest`、Node.js、Playwright QA。

## Global Constraints

- 不改变现有页面内容和布局，只给共享导航增加“模式验证”。
- 只监听 `127.0.0.1`，写入要求精确回环 Origin 和仅存内存的令牌。
- 不引入第三方 Python 或 JavaScript 依赖。
- v1 只注册 `historical-cycle-replay` 与 `forward-decision-observation`。
- 正式运行必须冻结模式快照和样本协议；失败、取消、中断、作废均不得原地重试。
- 证据和人工评审均绑定命题；系统不得自动得出命题或模式结论。
- 静态投影不得包含令牌、绝对路径、原始运行日志、失败审计正文或未审计产物。
- 页面沿用现站视觉，`DESIGN_VARIANCE: 3`、`MOTION_INTENSITY: 2`、`VISUAL_DENSITY: 8`。

---

### Task 1: 模式验证领域状态库

**Files:**
- Create: `scripts/mode_validation_state.py`
- Test: `tests/test_mode_validation_state.py`

**Interfaces:**
- Produces: `canonical_json(value) -> str`
- Produces: `content_hash(value) -> str`
- Produces: `ModeValidationStore(path: Path)` with `create_task`, `confirm_proposition`, `create_run`, `qualify_candidate`, `queue_run`, `finish_run`, `invalidate_run`, `append_review`, `snapshot_rows`
- Produces: `draft_propositions(mode: dict) -> list[dict]`
- Produces: `audit_evidence(context: dict) -> tuple[str, list[str]]`

- [ ] **Step 1: Write failing schema and lifecycle tests**

```python
class ModeValidationStoreTests(unittest.TestCase):
    def test_new_task_supersedes_the_existing_active_task_without_deleting_it(self): ...
    def test_confirming_a_proposition_requires_acceptance_criteria_and_falsifier(self): ...
    def test_run_immutable_fields_cannot_be_replaced(self): ...
    def test_review_events_append_and_supersede_without_update(self): ...
    def test_invalidated_dependency_marks_current_review_for_rereview(self): ...
```

- [ ] **Step 2: Run tests and verify the missing module failure**

Run: `python3 -m unittest tests.test_mode_validation_state -v`

Expected: FAIL because `mode_validation_state` does not exist.

- [ ] **Step 3: Implement canonical hashes, schema migration and strict enums**

```python
def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
```

Create all seven tables, foreign keys, partial unique active-task index and legal status transition checks. Use UTC ISO timestamps and UUID hex ids.

- [ ] **Step 4: Implement task, proposition, run, qualification and review methods**

Every public write method opens a short `BEGIN IMMEDIATE` transaction. Task replacement updates only status and supersession reference. Immutable run columns are inserted once; later methods update only lifecycle, result and invalidation columns allowed by the state machine.

- [ ] **Step 5: Implement evidence audit and derived risk rows**

```python
FAIL_REASONS = {
    "run_invalidated", "mode_hash_mismatch", "source_missing",
    "proposition_missing", "falsifier_missing", "non_finite_metric",
    "artifact_hash_mismatch", "exploratory_as_formal",
}
```

Failures win over warnings. Dependency invalidation must not update old review rows; `snapshot_rows` derives `needs_rereview`.

- [ ] **Step 6: Run focused tests, then the existing Python suite**

Run: `python3 -m unittest tests.test_mode_validation_state -v`

Expected: PASS.

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`

Expected: PASS.

### Task 2: 注册验证器和不可变产物

**Files:**
- Create: `scripts/mode_validation_validators.py`
- Test: `tests/test_mode_validation_validators.py`

**Interfaces:**
- Consumes: `content_hash`, `canonical_json`, `ModeValidationStore`
- Produces: `validator_catalog() -> list[dict]`
- Produces: `validate_validator_request(validator_id, parameters, run_kind) -> dict`
- Produces: `preview_historical_cycles(ledger_path, mode, protocol) -> list[dict]`
- Produces: `preview_forward_events(decision_events_path, confirmed_at, protocol) -> list[dict]`
- Produces: `execute_registered_run(store, run_id, paths, stop_requested) -> dict`

- [ ] **Step 1: Write failing registry and masking tests**

```python
class ValidatorRegistryTests(unittest.TestCase):
    def test_catalog_exposes_only_two_enabled_validators(self): ...
    def test_unknown_and_extra_parameters_are_rejected(self): ...
    def test_history_preview_omits_pnl_exit_and_retrospective_fields(self): ...
    def test_forward_preview_registers_every_dated_event_after_confirmation(self): ...
    def test_forward_deadline_cannot_be_extended_after_first_candidate(self): ...
```

- [ ] **Step 2: Verify tests fail because the registry is missing**

Run: `python3 -m unittest tests.test_mode_validation_validators -v`

Expected: FAIL on missing module.

- [ ] **Step 3: Implement fixed validator specifications**

```python
VALIDATORS = {
    "historical-cycle-replay": ValidatorSpec(
        version="1", run_kinds=("exploratory", "formal"),
        fields=("date_from", "date_to", "inclusion_rules", "exclusion_rules", "control_definition"),
    ),
    "forward-decision-observation": ValidatorSpec(
        version="1", run_kinds=("formal",),
        fields=("window_start", "window_end", "event_timing", "qualification_deadline", "inclusion_rules", "exclusion_rules"),
    ),
}
```

Reject arbitrary command, path or source-code fields and any undeclared key.

- [ ] **Step 4: Implement masked historical candidate collection**

Read complete cycles through existing ledger analytics. Emit only `source_ref`, `observed_at`, stock identity, first action date and whether it is independent from existing mode samples. Retain outcomes in an execution-only mapping that is not inserted until all qualifications are complete.

- [ ] **Step 5: Implement dated decision-event collection and deadline rules**

Parse Markdown headings with ISO dates. Use 15:00 Asia/Shanghai for same-day close and 09:30 on the next weekday for next-open defaults. Store every eligible heading once by deterministic source reference.

- [ ] **Step 6: Implement artifact writer and evidence result**

Write `run_card.json`, `candidate_manifest.json`, `result.json` and `publication_audit.json` under `reports/mode_validation/<mode>/<version>/<run_id>/` using create-new semantics. Hash every artifact. Never overwrite an existing file.

- [ ] **Step 7: Run validator and full Python tests**

Run: `python3 -m unittest tests.test_mode_validation_validators -v`

Expected: PASS.

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`

Expected: PASS.

### Task 3: 脱敏投影和静态页面构建

**Files:**
- Create: `scripts/mode_validation_projection.py`
- Modify: `scripts/build_personal_site.py`
- Create: `templates/personal_site/mode-validation.js`
- Modify: `templates/personal_site/site.css`
- Modify: `tests/test_personal_site.py`
- Create: `tests/test_mode_validation_projection.py`

**Interfaces:**
- Consumes: `ModeValidationStore.snapshot_rows`, validated trading modes
- Produces: `build_mode_validation_projection(db_path, trading_state, include_local_failures=False) -> dict`
- Produces: `render_mode_validation(data) -> str`
- Extends: `write_site(...)` return mapping with `mode_validation`

- [ ] **Step 1: Write failing projection privacy tests**

```python
class ProjectionTests(unittest.TestCase):
    def test_missing_database_returns_empty_read_only_projection(self): ...
    def test_failed_audit_body_and_absolute_artifact_path_are_not_published(self): ...
    def test_pass_with_warning_is_visible_but_cannot_satisfy_required_criterion(self): ...
```

- [ ] **Step 2: Write failing site generation assertions**

Extend the main site fixture to require `mode-validation.html`, `assets/mode-validation.js`, one new nav link, the five tabs, risk queue, read-only boot data and no write token.

- [ ] **Step 3: Verify focused tests fail for missing projection and page**

Run: `python3 -m unittest tests.test_mode_validation_projection tests.test_personal_site.PersonalSiteBuildTests -v`

Expected: FAIL because the page and projection do not exist.

- [ ] **Step 4: Implement fail-closed projection**

Return a stable shape containing `surface`, `modes`, `tasks`, `risk_queue`, `propositions`, `evidence`, `runs`, `reviews`, `validators` and `generated_at`. Normalize all source references to project-relative paths and omit failed evidence details.

- [ ] **Step 5: Add the standalone page and only one shared nav item**

Add `("mode_validation", "模式验证", "mode-validation.html")` to `NAV_ITEMS`. Render the context controls, risk queue and five tab panels with semantic HTML. Embed projection JSON in `<script type="application/json" id="modeValidationData">` and load only `assets/mode-validation.js` on this page.

- [ ] **Step 6: Implement accessible static interactions**

`mode-validation.js` reads inline projection, switches tabs with `aria-selected`, updates mode and task context, renders all data using DOM text nodes, and hides every `[data-local-write]` control until a local session succeeds. No HTML string is created from stored data.

- [ ] **Step 7: Add dense responsive CSS using existing tokens**

Use a two-column workbench at desktop and one column below 768px. Reuse 6px radii, existing focus rings and semantic colors. Add explicit loading, empty, error, read-only and pending styles. Do not add a new theme, font or accent.

- [ ] **Step 8: Run projection, site and privacy tests**

Run: `python3 -m unittest tests.test_mode_validation_projection tests.test_personal_site -v`

Expected: PASS.

Run: `python3 scripts/build_personal_site.py`

Expected: exits 0 and prints `mode_validation:`.

### Task 4: 回环本地工作台服务

**Files:**
- Create: `scripts/mode_validation_service.py`
- Test: `tests/test_mode_validation_service.py`

**Interfaces:**
- Consumes: store, validators, projection and `build_personal_site.write_site`
- Produces: `ModeValidationHTTPServer`
- Produces: `ModeValidationRequestHandler`
- Produces: CLI `python3 scripts/mode_validation_service.py --port 0`

- [ ] **Step 1: Write failing real-HTTP security tests**

```python
class ModeValidationServiceTests(unittest.TestCase):
    def test_non_loopback_origin_cannot_open_a_session(self): ...
    def test_write_requires_live_token_and_exact_origin(self): ...
    def test_close_and_expiry_revoke_write_capability(self): ...
    def test_request_body_over_256_kib_is_rejected(self): ...
```

Start the real server on an ephemeral port in a background thread and use `urllib.request`; do not mock the handler.

- [ ] **Step 2: Verify the missing service failure**

Run: `python3 -m unittest tests.test_mode_validation_service -v`

Expected: FAIL because the server module does not exist.

- [ ] **Step 3: Implement loopback Host, Origin and session lease checks**

Accept `127.0.0.1` and `[::1]` only. Generate a 32-byte URL-safe token on session open. Store `last_seen` in server memory. Heartbeat refreshes only a live matching token; close deletes it.

- [ ] **Step 4: Implement strict JSON router**

Map exact method and path patterns to service methods. Read at most 262145 bytes, reject malformed JSON and unknown fields, use stable error codes and never serialize tracebacks.

- [ ] **Step 5: Implement the serial worker and interruption recovery**

One daemon worker claims the oldest queued run in a transaction. At startup, change orphaned `running` rows to `failed` with `service_interrupted`. Queue cancellation changes only `queued`; running cancellation sets a stop request checked by the validator.

- [ ] **Step 6: Implement proposition, run, qualification, review and mode-change endpoints**

All formal write paths recheck current mode hash. Mode changes use a short-lived in-memory preview id plus the file's SHA-256, write through a same-directory temporary file, `fsync`, `os.replace`, and restore the original bytes if any later step fails.

- [ ] **Step 7: Run service and full Python tests**

Run: `python3 -m unittest tests.test_mode_validation_service -v`

Expected: PASS.

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`

Expected: PASS.

### Task 5: 本机写入体验和浏览器验收

**Files:**
- Modify: `templates/personal_site/mode-validation.js`
- Modify: `templates/personal_site/site.css`
- Modify: `tests/qa_personal_site.mjs`

**Interfaces:**
- Consumes: all local API routes and inline static projection
- Produces: visual task creation, proposition confirmation, run preview/confirmation, candidate qualification, run execution, review and invalidation controls

- [ ] **Step 1: Extend browser QA before implementing writes**

Add assertions for desktop and mobile that the page has no viewport overflow, risk queue precedes workbench, five tabs are keyboard reachable, static mode is read-only, selector and tabs work, and no token appears in URL or browser storage.

- [ ] **Step 2: Run QA and verify the new assertions fail**

Run: `python3 -m http.server 8765 --bind 127.0.0.1 --directory reports/personal_site`

In another shell run: `CODEX_PLAYWRIGHT_MJS=/path/to/playwright/index.mjs node tests/qa_personal_site.mjs http://127.0.0.1:8765 reports/personal_site/qa`

Expected: FAIL on missing mode-validation behaviors.

- [ ] **Step 3: Implement local API client and session lifecycle**

Open a session only on a loopback page. Keep the token in a module closure, heartbeat every 15 seconds, close with `sendBeacon` where available, and render an explicit session-expired state after any 403.

- [ ] **Step 4: Implement contextual write forms**

Use native `<dialog>` only if supported with an inline fallback. Every field has a visible label. Show exact preview before task/run/mode changes, disable double submission, keep errors beside the initiating control, and refresh the snapshot after success.

- [ ] **Step 5: Implement candidate qualification and append-only review controls**

Require exclusion reason, show deadline and overdue state, prevent outcome reveal until all candidates are non-pending, and show the prior review event when adding a superseding verdict.

- [ ] **Step 6: Run browser QA at both viewports**

Expected: report contains only `true` checks and the existing expected pool count.

### Task 6: 完整验证和交付审计

**Files:**
- Modify only files required by failures discovered below

**Interfaces:**
- Consumes: complete implementation
- Produces: fresh evidence that tests, build, privacy and browser behavior pass

- [ ] **Step 1: Run all Python tests**

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`

Expected: PASS with zero failures and errors.

- [ ] **Step 2: Run all non-browser Node tests**

Run: `node tests/test_ledger_filter.js`

Run: `node tests/test_cloudflare_auth_worker.mjs`

Expected: both exit 0. Run Playwright QA separately with its required environment.

- [ ] **Step 3: Build the real private site**

Run: `python3 scripts/build_personal_site.py`

Expected: exit 0 and all eight existing page keys plus `mode_validation` and `data` are printed.

- [ ] **Step 4: Run deployment preparation and bundle privacy checks**

Run: `python3 scripts/prepare_cloudflare_deploy.py --source reports/personal_site --worker deploy/cloudflare/worker.mjs --output /private/tmp/personal-trading-coach-mode-validation-deploy`

Run: `find /private/tmp/personal-trading-coach-mode-validation-deploy -type f \( -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.db' -o -name '*.csv' -o -name '*.pdf' -o -name '*.xlsx' \) -print`

Run: `rg -n "file://|/Users/|X-Workbench-Token|mode_validation\.sqlite" /private/tmp/personal-trading-coach-mode-validation-deploy || true`

Expected: preparation exits 0 and both scans print no private file, absolute path, token or database reference.

- [ ] **Step 5: Run Playwright QA and inspect screenshots**

Run QA at 1440x1080 and 390x844, inspect the generated `mode-validation-desktop.png` and `mode-validation-mobile.png`, and verify no clipping, hidden actions, contrast failures or accidental horizontal page scroll.

- [ ] **Step 6: Run source hygiene checks**

Run: `git diff --check`

Run: `rg -n "TO[D]O|TB[D]|file://|/Users/|X-Workbench-Token.*(localStorage|sessionStorage)|[—–]" templates/personal_site/mode-validation.js docs/superpowers/specs/2026-08-12-mode-validation-workbench-design.md`

Expected: no accidental placeholders, private paths, persistent token use, or forbidden dash characters in the new visible page copy.

- [ ] **Step 7: Review the final diff against the specification**

Confirm each acceptance criterion maps to a passing test or a fresh visual check. Report any intentionally deferred item explicitly; do not imply future coach-desk integration is part of v1.
