# Production Onboarding, Worker, Knowledge, and Trace Design

## Goal

Bring Web Admin from internal MVP behavior to production acceptance for one or more PDD shops: authorization, product sync, knowledge publishing, RAG traceability, worker lifecycle, and eventual real PDD sending must be operable from the Web Admin without mock data or ambiguous states.

## Non-Negotiable Rules

- Do not treat `remote-*` login session IDs as formal shop IDs.
- Do not send PDD messages unless the shop AI state, worker state, and global PDD sending switch all allow it.
- Do not expose cookie, token, password, API key, authorization header, or DSN password in frontend responses, logs, docs, or committed files.
- Do not physically delete shops, SOPs, product knowledge versions, trace records, or sync jobs in the first production line; use archive/disable states.
- Web API issues commands and stores desired state; it must not own long-running worker child processes.
- noVNC is the manual verification path. Playwright is an automatic renewal path only when explicit encrypted password credentials are available.

## Authorization Model

PDD authorization has two credential modes:

- `password_available`: the operator explicitly provides account and password for encrypted storage. noVNC is still used for first login or complex verification. Playwright may later attempt headless renewal with the stored credentials.
- `browser_only`: the operator logs in via QR code or does not provide a password. The system stores browser/profile/cookie authorization only. When authorization expires, the shop must move to `auth_required` and require noVNC renewal.

Authorization states:

- `unbound`: shop identity is not known yet.
- `valid`: shop identity and encrypted authorization are usable.
- `auth_required`: authorization expired or unavailable; manual noVNC login is required.
- `verification_required`: Playwright reached SMS, slider, QR, or other complex verification; manual noVNC continuation is required.
- `invalid_credentials`: encrypted password was attempted and rejected.
- `expired`: legacy/read-only expired state; should be normalized to `auth_required` for operations.

Playwright renewal may:

- reuse persistent profile/cookie data;
- input encrypted account/password when the operator has explicitly saved them;
- validate login state and refresh encrypted shop_auth;
- stop immediately when complex verification appears.

Playwright renewal must not:

- guess or recover a noVNC-entered password;
- auto-solve SMS, slider, QR, or captcha;
- retry indefinitely after a verification or credential failure;
- log credentials or cookie material.

## Worker Management Model

Web Admin controls worker desired state through API commands. A separate Worker Manager service owns actual process lifecycle.

Flow:

```text
Web UI -> Web API -> worker_control_commands / shop_worker_desired_state
      -> Worker Manager service -> per-shop worker process
      -> worker_status / worker_events -> Web API -> Web UI
```

Worker states shown to operations:

- `stopped`: stopped by operator or disabled state.
- `starting`: manager accepted a start command and is launching.
- `running`: worker process is alive and account is connected or processing.
- `stopping`: stop command accepted.
- `stale`: status heartbeat timed out.
- `failed`: process failed unexpectedly.
- `auth_required`: worker paused because PDD authorization needs noVNC renewal.
- `verification_required`: worker paused because Playwright encountered complex verification.
- `invalid_credentials`: worker paused because encrypted password is wrong or rejected.
- `disabled`: shop AI or worker desired state is disabled.

Web API endpoints:

- `POST /api/shops/{shop_id}/worker/start`
- `POST /api/shops/{shop_id}/worker/stop`
- `POST /api/shops/{shop_id}/worker/restart`
- `GET /api/shops/{shop_id}/worker-status`
- `GET /api/worker/events`

The first production line can implement Worker Manager as a local service that polls SQLite command tables. Later it can be moved to a queue or process supervisor without changing Web UI contracts.

## Message Processing and Sending Guard

Inbound PDD messages flow through:

```text
PDD WebSocket -> inbound queue -> duplicate guard -> AI/RAG/LLM -> guardrail -> outbox -> PDD send
```

The sending guard must require all conditions:

- global `PDD_SENDING_ENABLED=true`;
- shop AI enabled;
- worker account state is `running`;
- shop auth state is `valid`;
- no human lock blocks the buyer/conversation;
- safety guard permits sending.

If auth becomes invalid during receive or send:

- stop processing the affected account;
- mark auth state as `auth_required`, `verification_required`, or `invalid_credentials`;
- mark pending outbox items as blocked by auth;
- send PushPlus notification if configured;
- show Chinese remediation in Web Admin.

## Knowledge Center Scope

The old standalone SOP Management tab is removed. SOP is managed only inside Knowledge Center.

SOP states:

- `draft`: editable, not effective.
- `published_pending_index`: released snapshot exists but index has not succeeded.
- `indexing`: real index task is running.
- `index_failed`: index failed; not effective.
- `active`: indexed and effective for AI.
- `archived`: hidden from active operation and excluded from RAG.

SOP operations:

- create;
- edit;
- save draft;
- publish version;
- run real index;
- view chunks;
- view index failure;
- set or show active version;
- archive;
- restore to draft.

## Product Knowledge Scope

Product Knowledge must support full operations:

- search and filter product knowledge;
- view synced raw PDD fields;
- edit manual enrichment fields;
- save draft;
- publish version;
- run real index;
- view generated chunks;
- view recent RAG hits;
- archive or restore product knowledge;
- preserve previous versions and current active version.

Product states:

- `synced`: raw PDD product data is present.
- `draft`: manual enrichment exists but is not effective.
- `published_pending_index`: version published but not indexed.
- `indexing`: real index task running.
- `index_failed`: index failed.
- `active`: indexed and effective.
- `archived`: excluded from active lists and RAG.

Top filter bar fields:

- keyword: goods name, goods ID, shop name, manual notes;
- shop;
- product knowledge status;
- index status;
- missing field: price, specs, usage, ingredients, shelf life, warnings, manual notes;
- updated range;
- sort: latest updated, goods ID, goods name, index failure first, missing coverage first;
- page and page size.

The frontend must call backend paginated APIs; it must not rely on client-side filtering for production data.

## Trace and Operational Logs

Trace UI must be operation-readable by default and raw JSON only as a collapsed fallback.

Every message detail should show:

- buyer message;
- AI reply;
- shop and buyer context;
- recognized intent;
- whether LLM was called;
- model name;
- whether embedding and pgvector were used;
- RAG hit count;
- formal knowledge chunks;
- temporary context chunks;
- prompt used for generation;
- raw model response;
- guardrail result;
- whether PDD was sent;
- outbox status;
- retry count;
- human transfer reason;
- trace ID.

Chinese labels are required for non-technical operators. Technical keys may remain visible in secondary detail.

## Dashboard Scope

Dashboard must be backed by real APIs only. Required cards:

- total shops;
- valid authorization count;
- auth required count;
- AI enabled shops;
- running worker shops;
- stale/failed worker shops;
- product knowledge count;
- active SOP count;
- today inbound message count;
- today AI reply count;
- today real PDD send count;
- today blocked/no-send count;
- RAG hit rate;
- LLM error count;
- outbox pending/retry count;
- human transfer count.

No old fixed values such as static message count, static RAG hit rate, or static alerts may remain.

## Frontend Layout Principles

- Long product names and trace fields must not be crammed into narrow table cells.
- Use list/detail layouts for dense objects.
- Use a top filter bar for search-heavy pages.
- Use Chinese status badges and next-action text.
- Keep raw JSON collapsed.
- Preserve page state and filters in URL query or persisted view state.
- Store onboarding progress server-side so returning to the page restores the current shop flow.

## Acceptance Gates

- noVNC login can establish valid shop_auth and true PDD shop ID.
- Playwright renewal succeeds only when encrypted password is available and no complex verification is required.
- Playwright failure transitions to clear auth states and PushPlus notification.
- Worker can be started/stopped/restarted from Web Admin through Worker Manager, not as a Web API child process.
- Worker receives a real buyer message in controlled testing.
- With PDD sending disabled, no message is sent.
- With PDD sending enabled for one test shop, outbox and send result are observable.
- SOP and product chunks can be viewed and traced in RAG.
- Dashboard contains no mock strings or fixed metrics.
