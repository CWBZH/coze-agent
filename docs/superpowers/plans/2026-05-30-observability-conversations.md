# Observability Conversations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-style Web Admin observability page grouped by buyer user_id, with each message exposing chain nodes, prompt context, RAG chunks, reply generation, send/retry state, and timings.

**Architecture:** Read durable runtime data from SQLite (`pdd_inbound_message_queue`, `pdd_reply_outbox`) and optionally enrich it from private trace JSON files when available. Expose read-only Web API endpoints under `/api/observability`, then refactor the existing Trace Logs page into a buyer-conversation view. Keep full message/reply content in the business DB and private diagnostics, while normal logs remain metadata-only.

**Tech Stack:** FastAPI, SQLite, Pydantic-style dictionaries, React, TypeScript, CSS.

---

### Task 1: Backend Observability Service

**Files:**
- Create: `web_api/services/observability_service.py`
- Create: `web_api/routes/observability.py`
- Modify: `web_api/deps.py`
- Modify: `web_api/main.py`

- [ ] Create a service that joins inbound rows, outbox rows, and debug trace JSON by `trace_id`.
- [ ] Group conversation summaries by `shop_id + buyer_id`.
- [ ] Return message details with `buyer_message`, `generated_reply`, `send_text`, `send_status`, `retry_count`, `pdd_error_code`, `rag_chunks`, `prompt`, `raw_response`, `nodes`, and `timing`.
- [ ] Register API routes:
  - `GET /api/observability/conversations`
  - `GET /api/observability/conversations/{buyer_id}/messages`
  - `GET /api/observability/traces/{trace_id}`

### Task 2: Frontend API Client

**Files:**
- Create: `web_frontend/src/api/observability.ts`

- [ ] Add typed API helpers for conversation list, buyer message list, and trace detail.
- [ ] Keep returned records flexible enough to display partial trace data.

### Task 3: Trace Logs Page Refactor

**Files:**
- Modify: `web_frontend/src/views/TraceLogs.tsx`
- Modify: `web_frontend/src/components/TracePanel.tsx`
- Modify: `web_frontend/src/styles/globals.css`

- [ ] Replace flat trace list with buyer conversation list.
- [ ] Show per-message cards with actual buyer message, AI reply, send text, send status, retry state, and timing.
- [ ] Add per-message tabs: chain nodes, context, RAG chunks, reply generation, send/retry, technical fields.
- [ ] Use Chinese labels for operational status and explanations.
- [ ] Keep technical JSON available in a collapsed section.

### Task 4: Verification

**Files:**
- Test: existing test suite where relevant.

- [ ] Run Python compile for new backend files.
- [ ] Run frontend build.
- [ ] Run targeted API smoke if feasible.
- [ ] Commit and push to `deploy/web-admin-mvp`.

