# T102-D Conversation Context DB Probe

Date: 2026-05-21

## Purpose

T102-D adds a read-only probe for local SQLite conversation history schema. The
probe is used to confirm whether the current DB has enough table and field
coverage for `SQLiteConversationContextRepository`.

It does not write DB, does not call FastGPT or LLM, and does not send PDD
messages.

## Command

```text
python scripts/acceptance/conversation_context_schema_probe.py --db-path temp/channel_shop.db --json-only
```

Optional isolation probe:

```text
python scripts/acceptance/conversation_context_schema_probe.py --db-path temp/channel_shop.db --shop-id <shop_id> --buyer-id <buyer_id> --session-id <session_id> --json-only
```

Do not paste real buyer messages, cookies, tokens, API keys, or authorization
headers into the command.

## Output

The JSON output includes:

- `status`
- `candidate_conversation_tables`
- `candidate_message_tables`
- `detected_conversation_columns`
- `detected_message_columns`
- `supported_mapping`
- `missing_required_fields`
- `sample_counts`
- `isolation_probe_status`

The probe never outputs raw DB rows or message content.

## Supported Mapping

Conversation tables:

- `conversations`
- `conversation`

Message tables:

- `messages`
- `conversation_messages`

Required concepts:

- `shop_id`
- `buyer_id` / `customer_uid` / `from_uid`
- `session_id`
- `content` / `message` / `text` / `body`
- `created_at` / `created_time` / `timestamp` / `time`

`user_id` is optional in the schema probe, but when a runtime lookup provides
`user_id`, the repository requires it to participate in filtering if the table
contains the column.

## Gate Integration

The local internal gate can run an optional conversation smoke:

```text
python scripts/acceptance/run_internal_engine_gate.py --conversation-db-path temp/channel_shop.db --json-only
```

Default gate behavior does not require a real DB. Missing DB is reported as
`conversation_schema_status=missing` and does not fail the gate unless a future
task enables a stricter requirement.

The gate summary includes:

- `conversation_smoke_status`
- `conversation_schema_status`
- `history_message_count`
- `history_window_size`
- `pending_human`

## Acceptance Boundary

Passing this probe means the local DB shape is compatible enough for read-only
history loading. It does not mean the internal backend is production enabled.
The default backend remains `fastgpt`; `internal` remains explicit only.
