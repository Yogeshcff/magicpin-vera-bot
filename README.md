# Vera Merchant AI — Submission

## Approach
A deterministic, context-grounded composer organized by trigger family. Each message uses only facts available in CategoryContext, MerchantContext, TriggerContext and (when customer-facing) CustomerContext. The engine prioritizes concrete numbers/dates/headlines, existing active offers, customer history, and trigger-specific next actions.

## Design choices
- Trigger-specific handlers instead of one generic prompt.
- Customer-facing messages are separated from merchant-facing messages and use merchant attribution.
- No invented offers, research citations, competitor details, or customer facts.
- Active offers are preferred; expired offers are never promoted.
- Performance alerts cite the supplied metric/delta/baseline.
- Planning intents continue the merchant's request rather than asking redundant discovery questions.
- Explicit negative replies end the conversation; deferrals back off; affirmative replies continue with a concrete next step.
- In-memory state is used for the challenge API; `/v1/context` is idempotent by `(scope, context_id, version)`.

## Files
- `bot.py` — core `compose()` implementation.
- `server.py` — FastAPI wrapper implementing `/v1/context`, `/v1/tick`, `/v1/reply`, `/v1/healthz`, `/v1/metadata`.
- `submission.jsonl` — canonical 30 test outputs.

## Tradeoff
The solution favors deterministic grounding and latency over an external LLM dependency. This avoids hallucinations and makes identical contexts produce identical outputs. A production version could add an LLM only after deterministic retrieval/validation, with strict structured-output and fact-grounding checks.
