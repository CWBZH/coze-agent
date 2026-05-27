# T103-A History-Aware Answer Generator Offline Foundation

Date: 2026-05-21

## Scope

T103-A adds an offline foundation for a future history-aware internal answer
generator. It does not call a real LLM, does not call FastGPT, does not send PDD
messages, and does not change the production default backend.

The default remains `AI_WORKFLOW_BACKEND=fastgpt`. The internal backend and the
answer generator are only used when explicitly configured or injected in no-send
tools.

## Target Reply Model

Final automated replies should not be fixed SOP text only. The target internal
shape is:

- pending-human and redline paths are deterministic and transfer to human;
- normal product and SOP-domain paths may use product hits, SOP records, safe
  history summaries, and an LLM draft;
- every draft must pass `OutputGuardrail` before it can be treated as a reply.

## New Interfaces

`Message/workflow/answer_generator.py` defines:

- `AnswerGenerationContext`
- `AnswerDraft`
- `AnswerGenerator`
- `FakeAnswerGenerator`
- `NullAnswerGenerator`

`FakeAnswerGenerator` is deterministic and used only for tests and no-send
acceptance. `NullAnswerGenerator` represents disabled generation.

## Prompt Builder

`Message/workflow/prompt_builder.py` builds a `PromptPayload` with:

- `system_instructions`
- `context_blocks`
- `user_task`
- `output_format`
- `redaction_summary`
- `prompt_hash`

Only `prompt_hash`, counts, and safe metadata should appear in traces or
artifacts. Full prompt payloads must not be logged.

Intent constraints include:

- logistics: do not invent concrete delivery or shipment status;
- after-sales: do not promise refund, reshipment, compensation, or exchange
  approval;
- promotion: do not promise private discounts, gifts, or price adjustments;
- redline: do not judge authenticity, liability, compensation, or platform
  outcome;
- sensitive user safety: do not make deterministic medical or safety claims;
- product basic: answer from product knowledge and defer price to product or
  checkout page.

## Internal Engine Wiring

`InternalWorkflowEngine` accepts optional `answer_generator`.

The generator is not called for:

- pending-human lock;
- explicit human request;
- human escalation redline.

The generator may be called for:

- `product_basic` when product hits exist;
- SOP-backed logistics, after-sales, promotion, and sensitive-user domains.

All generated drafts go through `OutputGuardrail`.

## Safe Trace Fields

T103-A adds metadata-only trace fields:

- `answer_generator`
- `answer_generation_source`
- `answer_confidence`
- `used_history_count`
- `prompt_hash`
- `guardrail_status`

Forbidden in logs, traces, and artifacts:

- full buyer message;
- full history text;
- full answer text;
- full product detail;
- full SOP body;
- full prompt;
- raw provider response;
- keys, tokens, cookies, authorization headers, or other secrets.

## No-Send Commands

Fake generator dry-run:

```text
python scripts/acceptance/internal_backend_dry_run.py --shop-id synthetic-shop-1 --message "Mini Balm product price" --fake-product --use-fake-answer-generator --json-only
```

Dangerous draft guardrail smoke:

```text
python scripts/acceptance/internal_backend_dry_run.py --shop-id synthetic-shop-1 --message "Mini Balm product price" --fake-product --use-fake-answer-generator --fake-answer-dangerous --json-only
```

Synthetic QA:

```text
python scripts/acceptance/internal_engine_synthetic_qa.py --sop-file docs/acceptance/fixtures/internal_sop_example.md --use-fake-answer-generator --json-only
```

## Before Real LLM

Before any real answer generator is connected, these must pass:

- no-send gate;
- artifact forbidden-field scan;
- output guardrail tests;
- conversation isolation tests;
- pending-human lock tests;
- comparison harness review.

