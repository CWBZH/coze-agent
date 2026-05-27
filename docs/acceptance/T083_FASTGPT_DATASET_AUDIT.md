# T083-A FastGPT Dataset ID Audit

Date: 2026-05-20

Scope: read-only audit of local SQLite shop / account dataset readiness. No Python code, database rows, FastGPT configuration, prompts, or `.env` files were modified.

## 1. Check Environment

- Workspace: `E:\develop\customer-agent-refactor-v3`
- Database file checked: `temp/channel_shop.db`
- Database mode: SQLite read-only connection
- Runtime assumption from T080/T082-C:
  - `FASTGPT_APP_ID` is reserved only and is not used by the current auto-reply runtime.
  - Current FastGPT auto-reply route depends on `FASTGPT_BASE_URL`, `FASTGPT_API_KEY` or DB `AppConfig` key `fastgpt:api_key`, per-shop `shops.fastgpt_dataset_id`, and generated `chatId`.

Sensitive data handling:

- `fastgpt_dataset_id` values are shown only as redacted prefix/suffix.
- `fastgpt:api_key` was checked only for presence, length, and hash.
- Account cookies, passwords, tokens, access tokens, and raw API keys were not queried or written into this report.

## 2. Shops Table Fields

Current `shops` table schema:

| Column | Type | Nullable | Notes |
| --- | --- | --- | --- |
| `id` | `INTEGER` | no | Primary key |
| `channel_id` | `INTEGER` | no | FK-like channel reference |
| `shop_id` | `VARCHAR(100)` | no | Platform shop id |
| `shop_name` | `VARCHAR(100)` | no | Shop display name |
| `shop_logo` | `VARCHAR(255)` | yes | Optional logo |
| `description` | `VARCHAR(255)` | yes | Optional description |
| `fastgpt_dataset_id` | `VARCHAR(100)` | yes | Current FastGPT dataset selector |
| `created_at` | `DATETIME` | yes | Created time |

Related account status field:

| Table | Column | Type | Notes |
| --- | --- | --- | --- |
| `accounts` | `status` | `INTEGER` | Current headless worker uses `status == 1` as candidate enabled account |

## 3. Dataset ID Coverage

Local database counts:

| Item | Count |
| --- | ---: |
| channels | 1 |
| shops | 2 |
| accounts | 2 |
| pinduoduo shops with present dataset id | 2 |
| pinduoduo shops missing dataset id | 0 |
| pinduoduo accounts with `status == 1` | 2 |

Dataset validity rules used for this audit:

- `None` -> missing
- empty / whitespace -> missing
- common placeholders such as `your-*`, `change-me`, `todo`, `placeholder`, `null`, `none` -> invalid placeholder
- any other non-empty string -> present

This is a format/readiness audit only. It does not verify that the remote FastGPT dataset exists, is populated, or contains correct business knowledge.

## 4. Missing Dataset Impact

Current `MessagePipeline.process()` behavior:

1. Resolves shop by platform `shop_id`.
2. Reads `shop["fastgpt_dataset_id"]`.
3. If the dataset id is missing after `.strip()`:
   - logs `missing dataset_id`,
   - sets conversation status to `pending_human`,
   - alerts human service with `action=missing_fastgpt_dataset_id`,
   - returns `action=transfer_human`,
   - does not make a successful FastGPT request.

Operational impact:

- Shops without `fastgpt_dataset_id` cannot enter the normal FastGPT reply route.
- Missing dataset id is fail-safe and routes to human, but it will reduce automation coverage.
- Each production shop expected to auto-reply must have a valid `fastgpt_dataset_id`.

## 5. Shops Ready For FastGPT

| channel | shop_id | shop_name | user_id | account_status | enabled_candidate | dataset_state | dataset_id_redacted | expected_route |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| pinduoduo | `323473738` | 美肌萌主驿站 | `163349769` | 1 | yes | present | `6a0854...6dcd` | FastGPT route |
| pinduoduo | `565617` | 佳琪如梦 | `713439` | 1 | yes | present | `6a0855...77b4` | FastGPT route |

## 6. Shops That Would Transfer To Human

No current pinduoduo shop in `temp/channel_shop.db` was found with missing, empty, or placeholder `fastgpt_dataset_id`.

If a future shop has missing dataset id, expected route is:

```text
shop missing fastgpt_dataset_id
  -> MessagePipeline action=transfer_human
  -> conversation status pending_human
  -> notification metadata action=missing_fastgpt_dataset_id
  -> no FastGPT request success
```

## 7. Risks

1. Dataset presence is not dataset quality.
   - This audit confirms only that dataset ids are configured locally.
   - It does not verify remote FastGPT dataset availability, product coverage, policy coverage, or answer quality.

2. Dataset id values are operationally sensitive.
   - They are not API secrets, but should still be treated as internal configuration.
   - Reports should use redacted ids unless full ids are required for an operator-only checklist.

3. Account `status == 1` is a candidate enabled signal.
   - Prior runtime notes indicate `status == 1` is used as a candidate startup filter, not a fully separate persisted `auto_reply_enabled` policy.

4. `fastgpt:api_key` is configured in `app_config`.
   - Presence was confirmed without printing the value.
   - If authentication fails, dataset coverage alone is insufficient.

## 8. T083-B Knowledge Coverage Checklist Recommendation

Recommended next checklist categories for each configured dataset:

- Product basics: price, specs, usage, ingredients, shelf life, suitable users.
- Product context: goods card / goods id / multi-turn follow-up.
- Logistics: shipment time, courier, delayed delivery, shipment reminder wording.
- Promotions: coupons, gifts, price negotiation, no-invention policy.
- After-sales: refund, exchange, damaged item, missing item, wrong item.
- Complaint redlines: bad review, platform complaint, 12315, fake product, compensation, media exposure.
- Manual-transfer triggers: explicit human request, uncertain answer, high-risk claims.
- Fallback behavior: timeout, empty answer, unsafe answer, missing dataset.
- Trace expectations: `trace_id`, `dataset_id` redaction policy, `chat_id`, final send status.

Suggested T083-B acceptance output:

- dataset coverage matrix per shop,
- representative synthetic test questions,
- expected answer source or expected transfer-to-human,
- no-invention checklist,
- minimum pass/fail threshold before production.
