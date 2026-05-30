# Project Memory

Last updated: 2026-05-30

## Current Objective

Build the Web Admin to production standard, not MVP. Current focus is productionizing:
- store onboarding
- product sync
- product knowledge
- SOP knowledge center
- real RAG / LLM / pgvector observability
- guarded PDD sending
- dashboard real metrics
- trace logs readable enough for operations

## Non-Negotiable Safety Rules

- Do not commit, document, log, print, or return raw passwords, cookies, tokens, authorization headers, API keys, DSN passwords, or other secrets.
- Store real secrets only in local environment variables, server environment files with restricted permissions, or approved secret store.
- Real integration tests may use real PDD shop credentials/cookies/shop_auth, real PostgreSQL/pgvector, real LLM providers, and real Ollama when explicitly needed.
- Default tests and default gate must not send PDD messages.
- Real PDD sending is controlled by `PDD_SENDING_ENABLED`; it must remain disabled unless the user explicitly requests a sending-path test.
- Worker startup and AI enablement remain explicit actions; do not start workers or enable AI automatically during integration testing.
- `remote-*` IDs must not become formal business `shop_id`; temporary remote session IDs are allowed only for remote browser session lifecycle.

## User Decisions

- Product is no longer developed to MVP standard; all new work should target production readiness.
- Multiple stores are in scope; multi-user permission is not current priority.
- Store deletion is not allowed in phase one; only archive is allowed.
- Old visible SOP Management tab should be removed; Knowledge Center SOP is the authoritative SOP workflow.
- Store onboarding page remains one-stop flow; Knowledge Center/Product Knowledge/Live Chat/Logs remain regular daily operations pages.
- Tests can use real providers locally/server-side, but do not expose raw secrets.
- User wants to eventually enable real PDD sending for production acceptance, but only through explicit guarded switch.

## Server / Runtime State Known From Conversation

- Public IP used in deployment: `106.52.232.205`
- Web frontend served by nginx from:
  `/home/ubuntu/apps/customer-agent-refactor-v3/web_frontend/dist`
- Web API systemd service:
  `customer-agent-web-api.service`
- Web API listens on:
  `0.0.0.0:8088`
- nginx proxies `/api/` to local Web API.
- noVNC public route uses port `6088`; backend noVNC service uses localhost websockify/browser components.
- `.env.web` on server contains pgvector/LLM/embedding config; do not copy secrets into repo.
- pgvector extension was installed and verified on PostgreSQL 14:
  extension version observed: `0.8.2`
- Doubao multimodal embedding endpoint shape that worked:
  `POST {DOUBAO_EMBEDDING_BASE_URL}/embeddings/multimodal`
  payload:
  `{ "model": "...", "input": [{ "type": "text", "text": "..." }] }`
  response shape:
  `{ "data": { "embedding": [...] } }`
- Doubao chat model was later configured and direct test returned success.
- Real no-send live chat test showed:
  - `engine_mode=real_internal`
  - `engine_adapter_status=ok`
  - `real_engine_called=true`
  - `connects_pgvector=true`
  - `calls_llm=true`
  - `sends_pdd=false`
  - `no_send=true`

## Current Local Branch / Git State

Working directory has many modified files from this session and previous session. Do not revert unrelated changes.

Important modified/new areas include:
- guarded PDD sending:
  - `utils/pdd_send_policy.py`
  - `Message/core/outbox_worker.py`
  - `Message/core/reliable_queue.py`
  - `Message/handlers/ai_handler.py`
  - tests around reliable queue/provider status
- dashboard:
  - `web_api/services/dashboard_service.py`
- product knowledge:
  - `web_api/services/product_service.py`
  - `web_api/routes/products.py`
  - `web_api/schemas/products.py`
  - `web_frontend/src/views/Products.tsx`
  - `web_frontend/src/api/products.ts`
- knowledge center / SOP / product overrides:
  - `web_api/services/knowledge_center_service.py`
  - `web_api/routes/knowledge_center.py`
  - `web_api/schemas/knowledge_center.py`
  - `web_frontend/src/views/KnowledgeCenter.tsx`
  - `web_frontend/src/api/knowledgeCenter.ts`
- trace/log observability:
  - `web_frontend/src/components/TracePanel.tsx`
  - `web_frontend/src/views/TraceLogs.tsx`
- shell/layout:
  - `web_frontend/src/components/Header.tsx`
  - `web_frontend/src/components/Sidebar.tsx`
  - `web_frontend/src/components/StatusBadge.tsx`
  - `web_frontend/src/styles/globals.css`

Untracked known files:
- `PROJECT_MEMORY.md`
- `docs/prototypes/`
- `utils/pdd_send_policy.py`

## Completed In Last Development Pass

- Frontend shell mojibake fixed:
  - `Header.tsx`
  - `Sidebar.tsx`
  - `StatusBadge.tsx`
- Dashboard backend rewritten as real metrics:
  - reads `shops/shop_auth`
  - reads `shop_ai_settings`
  - reads `traces` for RAG hit rate, LLM errors, guardrail count
  - reads `product_sync_jobs`
  - reads `knowledge_index_jobs`
  - reads `product_knowledge` count excluding archived when schema supports it
  - uses `PDD_SENDING_ENABLED` to show true send state
- Dashboard no longer uses old hardcoded metrics strings like 126/92% in source.
- Trace panel made readable and more operational:
  - shows LLM evidence
  - shows pgvector/embedding/RAG evidence
  - shows sends_pdd/no_send
  - shows formal chunk vs temporary session context
  - shows chunk id/source/version/hash/score/content/metadata
- Product Knowledge page was redesigned to reduce cramped table:
  - card/list layout
  - coverage panel
  - filters including archived
  - details show fields, raw JSON, chunks, RAG debug
- Old visible `SOP 管理` navigation was removed from sidebar; Knowledge Center remains SOP source.
- Mock/MVP/fake wording scan was cleared for common user-visible patterns.

## Verification Already Run Locally

Commands run and passed:
- Python compile for changed backend files.
- `python -m pytest tests/test_web_api_dashboard.py tests/test_web_api_mvp.py tests/test_web_api_provider_status.py tests/test_reliable_message_queue.py tests/test_web_api_knowledge_product.py -q`
  - result: `40 passed`
- Wider subset:
  `python -m pytest tests/test_web_api_dashboard.py tests/test_web_api_mvp.py tests/test_web_api_provider_status.py tests/test_reliable_message_queue.py tests/test_web_api_knowledge_product.py tests/test_web_api_product_sync.py tests/test_product_sync_service.py tests/test_web_api_shop_onboarding.py tests/test_shop_auth_security.py -q`
  - result: `66 passed`
- `npm run build` under `web_frontend`
  - passed
- `git diff --check`
  - passed; only LF/CRLF warnings from git, no whitespace errors
- `python scripts/acceptance/run_internal_engine_gate.py --json-only`
  - status passed
  - default gate confirmed `sends_pdd=false`, `calls_llm=false`, `connects_pgvector=false` for default no-real-provider path.

## Current Product Questions / Remaining Work

Still needs production-level completion:
1. Decide final navigation:
   - likely remove old standalone SOP Management route entirely or keep hidden legacy route only.
   - Knowledge Center should own SOP creation, publish, index, archive.
2. Product knowledge CRUD:
   - raw product sync fields are read-only.
   - manual enhancements are editable through overrides.
   - product delete should be archive-only.
   - need verify UX clearly explains raw vs manual override vs published/indexed version.
3. SOP lifecycle:
   - user asked why new SOP stays draft.
   - Need ensure Knowledge Center has explicit buttons/flow:
     save draft -> publish -> real index -> active/current knowledge.
   - Need consider if first phase should archive SOP, not hard delete.
4. RAG/log observability:
   - Trace panel now improved, but should be checked visually in browser.
   - Need ensure no row value overlap in narrow right pane.
   - Need add fields user asked for if missing:
     actual LLM provider/model, request elapsed, answer generation status, embedding provider, vector store, retrieved chunk count, prompt token-ish counts if available.
5. Live Chat correctness:
   - User asked if RAG chunk is fully assembled into context.
   - Need verify real prompt includes retrieved chunks from pgvector and not just temporary session context.
   - Real no-send test had formal SOP hit for after_sales_evidence and answered from it.
   - Need ensure product price questions hit formal product chunk and include price/specs.
6. Dashboard:
   - Backend now real; need verify frontend dashboard consumes `/api/dashboard/summary`, not old hardcoded local cards.
7. Real PDD sending:
   - Code path guarded by `PDD_SENDING_ENABLED`.
   - Need a separate production acceptance plan before enabling:
     enable one shop, one controlled buyer/session, one no-risk message, audit logs, rollback switch.
   - Do not enable by default.
8. noVNC connection failure:
   - User saw "无法连接到服务器" in noVNC iframe.
   - Need inspect service status/nginx/websockify if asked; likely session/browser service lifecycle issue.
9. Deployment:
   - Need commit/push if user asks.
   - Then server pull/build/restart.
   - Do not include secrets in commands.

## Useful Verification Commands

Local:

```powershell
python -m py_compile web_api\services\dashboard_service.py web_api\services\live_chat_service.py web_api\services\product_service.py
python -m pytest tests/test_web_api_dashboard.py tests/test_web_api_mvp.py tests/test_web_api_provider_status.py tests/test_reliable_message_queue.py tests/test_web_api_knowledge_product.py tests/test_web_api_product_sync.py tests/test_product_sync_service.py tests/test_web_api_shop_onboarding.py tests/test_shop_auth_security.py -q
Push-Location web_frontend; npm run build; Pop-Location
git diff --check
python scripts/acceptance/run_internal_engine_gate.py --json-only
```

Server deployment skeleton:

```bash
cd /home/ubuntu/apps/customer-agent-refactor-v3
git fetch origin
git checkout deploy/web-admin-mvp
git pull --ff-only origin deploy/web-admin-mvp
source .venv/bin/activate
python -m py_compile web_api/services/*.py web_api/schemas/*.py web_api/routes/*.py
sudo systemctl restart customer-agent-web-api
cd web_frontend
npm install
npm run build
sudo nginx -t
sudo systemctl reload nginx
curl -s http://127.0.0.1/api/provider-status | python3 -m json.tool
curl -s http://127.0.0.1/api/dashboard/summary | python3 -m json.tool
```

## Notes For Future Agent

- Continue from local repo-check; do not assume pushed.
- Prefer concise updates in Chinese.
- Use `apply_patch` for file edits.
- Do not reveal secrets.
