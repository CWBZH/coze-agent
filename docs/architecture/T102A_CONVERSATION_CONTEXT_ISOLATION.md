# T102-A Conversation Context Isolation

Date: 2026-05-21

## Purpose

T102-A adds a read-only conversation context foundation for the future internal
LLM answer generator.

T102-A created the repository primitives. T102-B wires the repository into the
`InternalWorkflowEngine` only when that experimental backend is constructed
with an explicit `conversation_context_repository`. The production default
backend remains `fastgpt`.

## Interface

Module:

```text
Message/workflow/conversation_context.py
```

Core types:

- `ConversationMessage`
- `ConversationContext`
- `ConversationContextRepository`
- `InMemoryConversationContextRepository`
- `SQLiteConversationContextRepository`

Main method:

```python
load_context(shop_id, user_id, buyer_id, session_id, limit=6) -> ConversationContext
```

SQLite adapter constructor:

```python
SQLiteConversationContextRepository(db_path, timeout=None)
```

The SQLite adapter opens the database in read-only mode, closes the connection
after each load, and returns an empty context when the DB, required tables, or
required isolation fields are missing.

## Isolation Key

History lookup must be filtered by the full key:

```text
shop_id + user_id + buyer_id + session_id
```

Required isolation:

- no cross-shop history
- no cross-buyer history
- no cross-session history
- no cross-user history when `user_id` exists

The SQLite adapter refuses unsafe broad reads:

- `shop_id`, `buyer_id`, and `session_id` must be present.
- `user_id` participates in filtering when provided.
- Missing required identity columns return an empty context instead of falling
  back to a weaker query.

Compatible table/field concepts:

- conversation tables: `conversations`, `conversation`
- message tables: `messages`, `conversation_messages`
- conversation id: `conversation_id`, `id`
- buyer id: `buyer_id`, `customer_uid`, `from_uid`
- content: `content`, `message`, `text`, `body`
- created time: `created_at`, `created_time`, `timestamp`, `time`

## History Window

The history window keeps the latest N messages after filtering and sorts them
by `created_at` in stable chronological order.

Messages expose:

- `role`
- `message_type`
- `content_summary`
- `content_hash`
- `created_at`
- `source`

`content_summary` is metadata-only. It uses length and hash and must not store
the full buyer message or full seller/AI reply.

## Human State

`ConversationContext` can represent:

- `human_state`
- `pending_human`
- `last_intent`
- `last_action`
- `history_message_count`

This allows future answer generation to avoid responding normally while a
conversation is already pending human handling.

## T102-B Internal Wiring

`InternalWorkflowEngine` now accepts an optional dependency:

```python
InternalWorkflowEngine(conversation_context_repository=repo)
```

When present, the engine loads history using:

```text
shop_id + user_id + buyer_id/customer_uid + session_id
```

The loaded history is attached to `WorkflowContext.history` using only:

- `role`
- `message_type`
- `content_summary`
- `content_hash`
- `created_at`
- `source`

The result trace exposes only hashed or aggregate fields:

- `history_message_count`
- `history_window_size`
- `pending_human`
- `conversation_id_hash`
- `session_id_hash`
- `buyer_id_hash`
- `user_id_hash`
- `history_source`

If `pending_human=True`, the internal engine returns:

- `action=transfer_human`
- `intent=pending_human_lock`
- `reason=pending_human_conversation`

This happens before product repository lookup, SOP/domain response, or intent
classifier execution. It does not change pipeline-level block/media handling.

## No-Send Dry Run

The no-send dry-run helper supports synthetic history checks:

```text
python scripts/acceptance/internal_backend_dry_run.py --shop-id synthetic-shop-1 --message "product price" --with-fake-history --json-only
python scripts/acceptance/internal_backend_dry_run.py --shop-id synthetic-shop-1 --message "product price" --pending-human --json-only
```

Explicit fake history messages:

```text
python scripts/acceptance/internal_backend_dry_run.py --shop-id synthetic-shop-1 --message "how to use it" --history-message buyer:"what specs does it have" --history-message seller:"it has multiple specs" --json-only
```

`--history-message` accepts `buyer`, `seller`, `ai`, or `system` roles. When fake history and `--use-conversation-db` are both provided, fake history wins so manual dry-runs remain deterministic.

SQLite conversation smoke:

```text
python scripts/acceptance/internal_backend_dry_run.py --shop-id synthetic-shop-1 --message "product price" --use-conversation-db --conversation-db-path temp/missing-conversation-test.db --json-only
```

Additional DB options:

- `--conversation-db-path`
- `--conversation-session-id`
- `--conversation-buyer-id`

Schema probe:

```text
python scripts/acceptance/conversation_context_schema_probe.py --db-path temp/channel_shop.db --json-only
```

The output contains only history counts, source, hashed identifiers, and schema compatibility summaries. It never includes raw DB rows or message content.

## Future Answer Generation

T103-A adds only the offline foundation for a future history-aware answer
generator. Conversation history may be passed as sanitized `content_summary` and
`content_hash` entries. Normal logs and acceptance artifacts must not contain
full history text or full generated replies.

Before a real LLM answer generator is enabled, conversation isolation,
pending-human lock behavior, output guardrail tests, no-send gate, and artifact
scan must all pass.

Forbidden in logs, trace, and artifacts:

- full buyer message
- full seller or AI reply
- raw DB row
- token/cookie/access_token/authorization/api_key/secret
