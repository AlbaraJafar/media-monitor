# Architecture Note

## Components

```
n8n (schedule, 5 min) → POST /ingest  → feedparser + trafilatura → Postgres (articles)
                                       → embed + cluster near-duplicates (pgvector)
n8n (schedule, 5 min) → POST /classify → per-article structured LLM call (4 themes,
                                          sentiment, priority, risk_score) → Postgres
                                       → risk_score ≥ 0.7 → alerts table
n8n (webhook, on new alert) → notify on-call analyst (Slack) → ack
n8n (schedule, 05:30 daily) → POST /brief → draft (LLM, cited) → verify (LLM,
                                          claim-by-claim against source) → Postgres
                                       → send-and-wait approval to named analyst
                                       → on approve → POST /brief/{id}/deliver → Slack/email
Analyst → n8n chat trigger → POST /ask → hybrid retrieval (BM25 + embeddings) → answer
```

## Model choice and cost

Two-tier model use: a smaller/cheaper model for the high-volume per-item
classification step (~900 calls/day after dedup), and a stronger model for
briefing generation and the claim verifier (1-2 calls/day). This keeps the
per-item cost low where volume is high, and spends more compute only where
reasoning quality matters most (a briefing the Director General reads).

Estimated monthly run cost at ~1,500 items/day (before dedup): low hundreds of
USD, dominated by the classification step. See the cost breakdown slide for
the itemized arithmetic — verify current provider pricing before presenting
firm numbers.

Model versions are pinned in `app/config.py`. The evaluation set is re-run
whenever a model version changes, since judge/classifier calibration can
drift silently across model updates.

## Data handling and security

- **Public news only** in this prototype — acceptable to route through a hosted
  LLM API.
- **Internal/confidential documents (production path, not built here):** would
  stay inside the client's environment — in-Kingdom or private model endpoint,
  no vendor training/retention — never sent to a general hosted API.
- **Access control at retrieval time:** production design attaches an ACL to
  every indexed chunk and filters in the retrieval query itself, not after
  generation, so a restricted document can't leak into an answer to an
  unauthorized user.
- **Prompt injection:** ingested article text is untrusted input. It is passed
  as data inside a delimited block, the classification/briefing steps have no
  tool access, output is schema-constrained, and the verifier double-checks
  claims — so a hostile phrase embedded in a scraped article can't hijack the
  pipeline's behavior.
- **Human sign-off is enforced technically, not just procedurally:** only a
  briefing with status=`approved` (set via the `/approve` endpoint by a named
  analyst) can be delivered; `/deliver` rejects anything else.
- **Audit trail:** `approved_by`, `approved_at`, and the exact `content_md`
  that was approved are stored — traceable if a Director asks "who approved
  this."
- Secrets via `.env` / a secrets manager in production, never committed.

## Failure handling — the "06:45" story

1. Briefing generation is scheduled for 05:30, not 06:30, to leave ~75 minutes
   of recovery buffer before the 07:30 deadline.
2. Each LLM call retries with backoff on transient API errors or malformed
   JSON (`services/llm.py`).
3. If generation still fails, the pipeline falls back to a secondary model
   (config-swappable).
4. If it still fails, a clearly labeled **DEGRADED** briefing is produced from
   whatever was successfully classified, with a banner stating what's missing
   (see `services/briefing.py: run_briefing` — empty-window fallback is the
   simplest case of this, extend the same pattern for partial failures).
5. The on-call analyst is paged if no usable draft exists by a checkpoint
   time, with the manual process as the last resort.
6. Nothing reaches the Director General without a human-approved status,
   degraded or not.

## Evaluation methodology

A hand-labeled gold set (`eval/gold_set.jsonl`, target ~120 items, including a
deliberate Arabic slice and ambiguous cases) is compared against what the
pipeline actually produced. `eval/run_eval.py` reports per-theme precision/
recall/F1 and, as the headline metric, alert recall/precision — since missing
a real reputational crisis is a worse failure than one false alarm. Briefing
faithfulness is checked by the claim-level verifier plus manual spot-checks of
a sample. Analyst corrections made at approval time are the intended feedback
loop for improving the gold set and, over time, the prompts.

## What I'd build next with two more weeks

1. Expand the gold set past 120 items and add an inter-annotator check.
2. Move access-control-at-retrieval from design to implementation, and pilot
   ingesting one internal document type under it.
3. Shadow-mode run against the manual process to measure real agreement
   before cutover.
4. Prompt-caching and batch-API use to reduce cost further at scale.
