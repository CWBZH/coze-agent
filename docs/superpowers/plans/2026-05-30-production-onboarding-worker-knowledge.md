# Production Onboarding Worker Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production Web Admin loop for PDD authorization renewal, Web-managed workers, canonical Knowledge Center SOP/product knowledge, operational trace visibility, and real dashboard metrics.

**Architecture:** Web API owns desired state, commands, schemas, and operator-facing APIs. A separate Worker Manager owns long-running worker processes. noVNC is the manual verification path; Playwright is a bounded renewal path only when encrypted credentials are available.

**Tech Stack:** FastAPI, SQLite migrations, React/Vite, Python runtime worker, Playwright, PushPlus, pgvector, Doubao embedding/LLM.

---

## File Map

- `web_api/services/schema_migration_service.py`: add production tables for worker control, worker events, credential mode, auth state details, product filters if missing.
- `web_api/services/shop_auth_service.py`: store credential mode and password availability metadata without exposing secrets.
- `web_api/services/shop_auth_resolver.py`: return auth state and credential mode for worker/product sync decisions.
- `Channel/pinduoduo/utils/base_request.py`: replace uncontrolled Playwright relogin with bounded renewal and auth-state transitions.
- `Channel/pinduoduo/pdd_login.py`: keep reusable Playwright login/refresh helpers; do not log credentials.
- `core/worker_alerts.py`: PushPlus alerts for auth required, verification required, invalid credentials, and worker failures.
- `runtime/worker_manager.py`: new manager loop that executes Web API commands and owns worker subprocess lifecycle.
- `runtime/worker.py`: emit auth-required/verification-required status and preserve queue behavior.
- `web_api/services/worker_control_service.py`: command API, desired state, status aggregation, event listing.
- `web_api/routes/worker_control.py`: Web worker control endpoints.
- `web_api/services/dashboard_service.py`: real dashboard metrics only.
- `web_api/services/product_knowledge_service.py` or existing knowledge service: product knowledge paginated filters and CRUD operations.
- `web_api/routes/products.py` and `web_api/routes/knowledge_center.py`: expose filters, CRUD, publish, archive, chunks, index status.
- `web_api/services/trace_service.py`: include operational trace fields and outbox/send details.
- `web_frontend/src/views/Products.tsx`: product search/filter bar and list/detail layout.
- `web_frontend/src/views/KnowledgeCenter.tsx`: canonical SOP and product publishing UI.
- `web_frontend/src/components/TracePanel.tsx`: operation-readable trace layout.
- `web_frontend/src/views/Dashboard.tsx`: real cards only.
- `web_frontend/src/views/Shops.tsx`: worker control buttons and auth remediation.
- `web_frontend/src/components/Sidebar.tsx`: remove old SOP Management entry.
- `tests/test_worker_control_api.py`: Web worker command and status coverage.
- `tests/test_worker_auth_renewal.py`: Playwright/noVNC auth state behavior.
- `tests/test_product_knowledge_filters.py`: product search/filter CRUD behavior.
- `tests/test_dashboard_real_metrics.py`: no mock dashboard metrics.
- `tests/test_trace_operational_view.py`: trace fields for LLM/RAG/PDD/outbox.

## Task 1: Schema and State Foundation

**Files:**
- Modify: `web_api/services/schema_migration_service.py`
- Modify: `web_api/services/shop_auth_service.py`
- Modify: `web_api/services/shop_auth_resolver.py`
- Test: `tests/test_schema_migrations.py`
- Test: `tests/test_shop_auth_resolver.py`

- [ ] **Step 1: Add failing migration tests**

Add tests that create an old SQLite database, run migrations twice, and assert:

```python
def test_worker_control_and_auth_state_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "web.db"
    service = SchemaMigrationService(db_path)
    first = service.run()
    second = service.run()
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "worker_control_commands" in tables
        assert "shop_worker_desired_state" in tables
        assert "worker_events" in tables
        columns = {row[1] for row in conn.execute("PRAGMA table_info(shop_auth)")}
        assert "credential_mode" in columns
        assert "auth_state_reason" in columns
        assert "last_auth_event_at" in columns
    assert second["applied"] == []
```

- [ ] **Step 2: Run the migration tests and confirm failure**

Run:

```bash
python -m pytest tests/test_schema_migrations.py::test_worker_control_and_auth_state_schema_is_idempotent -q
```

Expected: fails because tables/columns are not present.

- [ ] **Step 3: Implement idempotent migrations**

Add `CREATE TABLE IF NOT EXISTS` for:

```sql
worker_control_commands(id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, command TEXT NOT NULL, status TEXT NOT NULL, requested_by TEXT, requested_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, error_type TEXT, error_summary TEXT, trace_id TEXT)
shop_worker_desired_state(shop_id TEXT PRIMARY KEY, desired_state TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL, reason TEXT)
worker_events(id TEXT PRIMARY KEY, shop_id TEXT, event_type TEXT NOT NULL, status TEXT, summary TEXT, metadata_json TEXT, created_at TEXT NOT NULL, trace_id TEXT)
```

Add `ALTER TABLE shop_auth ADD COLUMN` guarded by `PRAGMA table_info` for:

```text
credential_mode TEXT DEFAULT 'browser_only'
auth_state_reason TEXT
last_auth_event_at TEXT
```

- [ ] **Step 4: Run migration and auth resolver tests**

Run:

```bash
python -m pytest tests/test_schema_migrations.py tests/test_shop_auth_resolver.py -q
```

Expected: all pass.

## Task 2: Bounded Playwright Renewal and Auth Required Transitions

**Files:**
- Modify: `Channel/pinduoduo/utils/base_request.py`
- Modify: `Channel/pinduoduo/pdd_login.py`
- Modify: `core/worker_alerts.py`
- Test: `tests/test_worker_auth_renewal.py`

- [ ] **Step 1: Write tests for browser-only expiration**

Test that an expired `browser_only` account does not import Playwright and instead marks auth required:

```python
def test_browser_only_expired_auth_marks_auth_required_without_playwright(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "web.db"))
    request = make_base_request_with_auth_state(credential_mode="browser_only", expired=True)
    result = request.handle_session_expired_for_test()
    assert result.status == "auth_required"
    assert result.retryable is False
    assert result.next_action == "open_remote_browser"
```

- [ ] **Step 2: Write tests for password renewal verification required**

```python
def test_password_renewal_stops_on_complex_verification(monkeypatch, tmp_path):
    monkeypatch.setattr("Channel.pinduoduo.utils.base_request.refresh_pdd_cookies", lambda *_: {"status": "verification_required"})
    request = make_base_request_with_auth_state(credential_mode="password_available", expired=True)
    result = request.handle_session_expired_for_test()
    assert result.status == "verification_required"
    assert result.next_action == "open_remote_browser"
```

- [ ] **Step 3: Implement auth transition helper**

Create a helper in `base_request.py` that updates `shop_auth.auth_status`, `auth_state_reason`, and `last_auth_event_at`, without writing cookies or passwords.

- [ ] **Step 4: Replace automatic relogin loop**

In `_relogin_and_update_cookies`, branch:

```python
if credential_mode != "password_available":
    return AuthRenewalResult(status="auth_required", next_action="open_remote_browser")
```

For password mode, call Playwright once. If verification appears, return `verification_required`. If password rejected, return `invalid_credentials`. No infinite retries.

- [ ] **Step 5: Add PushPlus alerts**

Use existing notification service patterns to send sanitized alert metadata:

```text
shop_id, username safe display, auth state, next action, trace_id
```

- [ ] **Step 6: Run worker auth tests**

Run:

```bash
python -m pytest tests/test_worker_auth_renewal.py tests/test_pushplus_notification.py -q
```

Expected: all pass.

## Task 3: Worker Manager and Web Control API

**Files:**
- Create: `runtime/worker_manager.py`
- Create: `web_api/services/worker_control_service.py`
- Create: `web_api/routes/worker_control.py`
- Modify: `web_api/main.py`
- Modify: `web_api/services/shop_onboarding_service.py`
- Test: `tests/test_worker_control_api.py`

- [ ] **Step 1: Write command API tests**

```python
def test_worker_start_command_creates_desired_state_and_command(client):
    response = client.post("/api/shops/565617/worker/start", json={"operator": "local_admin"})
    assert response.status_code == 200
    body = response.json()
    assert body["desired_state"] == "running"
    assert body["command"] == "start"
```

- [ ] **Step 2: Implement `WorkerControlService`**

Methods:

```python
request_start(shop_id: str, operator: str) -> dict
request_stop(shop_id: str, operator: str, reason: str | None = None) -> dict
request_restart(shop_id: str, operator: str, reason: str | None = None) -> dict
get_worker_status(shop_id: str) -> dict
list_events(shop_id: str | None, limit: int) -> dict
```

- [ ] **Step 3: Implement routes**

Routes:

```text
POST /api/shops/{shop_id}/worker/start
POST /api/shops/{shop_id}/worker/stop
POST /api/shops/{shop_id}/worker/restart
GET /api/shops/{shop_id}/worker-status
GET /api/worker/events
```

- [ ] **Step 4: Implement `runtime.worker_manager` polling skeleton**

The manager polls pending commands, launches/stops per-shop workers, writes events, and never exposes secrets.

- [ ] **Step 5: Run worker control tests**

Run:

```bash
python -m pytest tests/test_worker_control_api.py tests/test_worker_ai_enablement.py -q
```

Expected: all pass.

## Task 4: Product Knowledge Search, Filter, and CRUD

**Files:**
- Modify: `web_api/routes/products.py`
- Modify: `web_api/services/product_knowledge_service.py` or `web_api/services/knowledge_center_service.py`
- Modify: `web_frontend/src/views/Products.tsx`
- Modify: `web_frontend/src/styles/globals.css`
- Test: `tests/test_product_knowledge_filters.py`

- [ ] **Step 1: Add filter API tests**

```python
def test_products_filter_by_keyword_shop_status_and_missing_field(client):
    response = client.get("/api/products?keyword=祛斑&shop_id=565617&missing_field=usage&knowledge_status=synced&page=1&page_size=20")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
```

- [ ] **Step 2: Implement paginated backend filters**

Support query params:

```text
keyword, shop_id, knowledge_status, index_status, missing_field, has_manual_notes, updated_from, updated_to, sort, page, page_size
```

- [ ] **Step 3: Add product CRUD APIs if missing**

Ensure APIs exist for:

```text
GET detail
PATCH manual fields
POST publish
POST index
POST archive
POST restore
GET chunks
```

- [ ] **Step 4: Rework Products page layout**

Add top filter row with keyword, shop, status, index status, missing field, sort, query/reset buttons. Use list/detail layout so long names do not compress tables.

- [ ] **Step 5: Run frontend and API tests**

Run:

```bash
python -m pytest tests/test_product_knowledge_filters.py -q
cd web_frontend && npm run build
```

Expected: tests and build pass.

## Task 5: Canonical Knowledge Center SOP

**Files:**
- Modify: `web_frontend/src/components/Sidebar.tsx`
- Modify: `web_frontend/src/views/KnowledgeCenter.tsx`
- Modify: `web_api/services/knowledge_center_service.py`
- Test: `tests/test_knowledge_center_real_index.py`

- [ ] **Step 1: Confirm old SOP management entry is removed**

Assert sidebar does not contain the old route label `SOP 管理`.

- [ ] **Step 2: Add SOP state transition tests**

```python
def test_sop_draft_publish_index_archive_restore_flow(client):
    create = client.post("/api/knowledge/sop", json={"shop_id": "565617", "domain": "logistics_policy", "title": "物流 SOP", "content": "发货以订单物流页为准"})
    publish = client.post(f"/api/knowledge/sop/{create.json()['id']}/publish")
    archive = client.post(f"/api/knowledge/sop/{create.json()['id']}/archive")
    assert archive.status_code == 200
```

- [ ] **Step 3: Ensure SOP statuses are explicit**

Use status values:

```text
draft, published_pending_index, indexing, index_failed, active, archived
```

- [ ] **Step 4: Update UI copy**

Show Chinese lifecycle explanation: draft does not take effect; only indexed active version is used by AI.

- [ ] **Step 5: Run knowledge tests and frontend build**

Run:

```bash
python -m pytest tests/test_knowledge_center_real_index.py -q
cd web_frontend && npm run build
```

Expected: pass.

## Task 6: Operational Trace Layout

**Files:**
- Modify: `web_api/services/trace_service.py`
- Modify: `web_frontend/src/components/TracePanel.tsx`
- Modify: `web_frontend/src/views/TraceLogs.tsx`
- Test: `tests/test_trace_operational_view.py`

- [ ] **Step 1: Add trace service test**

```python
def test_trace_response_contains_operational_fields(client):
    trace = client.get("/api/traces/example").json()
    assert "calls_llm" in trace
    assert "connects_pgvector" in trace
    assert "retrieved_chunks" in trace
    assert "pdd_send_status" in trace
    assert "outbox_status" in trace
```

- [ ] **Step 2: Normalize trace labels and sections**

TracePanel sections:

```text
处理结论, 模型调用, RAG 命中, 发送状态, Prompt, 原始 JSON
```

- [ ] **Step 3: Fix narrow field layout**

Use CSS grid with minimum label/value widths and wrapping. Never overlap keys and values.

- [ ] **Step 4: Run trace tests and frontend build**

Run:

```bash
python -m pytest tests/test_trace_operational_view.py tests/test_web_api_internal_engine_adapter.py -q
cd web_frontend && npm run build
```

Expected: pass.

## Task 7: Dashboard Real Metrics

**Files:**
- Modify: `web_api/services/dashboard_service.py`
- Modify: `web_frontend/src/views/Dashboard.tsx`
- Test: `tests/test_web_api_dashboard.py`

- [ ] **Step 1: Add no-mock dashboard tests**

```python
def test_dashboard_metrics_are_derived_from_database(client):
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    text = response.text
    assert "本地诊断数据" not in text
    assert "WebSocket 曾断开" not in text
```

- [ ] **Step 2: Implement missing real metrics**

Use tables for shops, shop_auth, product_knowledge, knowledge_versions, trace logs, outbox, worker status/events.

- [ ] **Step 3: Update dashboard frontend**

Render empty-state cards when data is unavailable; never substitute hard-coded values.

- [ ] **Step 4: Run dashboard tests and string scan**

Run:

```bash
python -m pytest tests/test_web_api_dashboard.py -q
rg "126|92%|WebSocket 曾断开|本地诊断数据" web_frontend/src web_api docs tests
```

Expected: tests pass and scan has no production UI mock strings.

## Task 8: Deployment and Acceptance Documentation

**Files:**
- Modify: `docs/runtime/HEADLESS_WORKER_RUNBOOK.md`
- Modify: `docs/user_guide/WEB_ADMIN_USER_MANUAL.md`
- Create: `docs/acceptance/PRODUCTION_WEB_ADMIN_ACCEPTANCE.md`

- [ ] **Step 1: Document worker manager deployment**

Include systemd unit names, env vars, healthcheck commands, stop/start behavior, and no secrets.

- [ ] **Step 2: Document operator flow**

Cover first noVNC login, Playwright renewal, auth_required remediation, product sync, knowledge publish, no-send validation, AI enablement, worker start, real send smoke.

- [ ] **Step 3: Document acceptance checklist**

Include commands and browser checks:

```bash
python -m pytest tests/test_worker_control_api.py tests/test_worker_auth_renewal.py tests/test_product_knowledge_filters.py tests/test_trace_operational_view.py tests/test_web_api_dashboard.py -q
cd web_frontend && npm run build
git diff --check
```

- [ ] **Step 4: Run doc and diff checks**

Run:

```bash
git diff --check
rg "cookie|password|token|authorization|access_token|api_key|secret|postgresql://" docs web_api web_frontend/src tests
```

Expected: no newly introduced secrets; documentation uses placeholders only.

## Plan Self-Review

- The plan covers auth renewal, noVNC fallback, worker control, product knowledge filters/CRUD, SOP consolidation, trace layout, dashboard real metrics, and deployment docs.
- The plan intentionally keeps Web API separate from worker process ownership.
- The plan avoids physical deletion and uses archive/desired-state transitions.
- The plan requires tests for each production-facing behavior before final acceptance.
