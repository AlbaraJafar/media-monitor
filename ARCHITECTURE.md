# Architecture Note

## Components

```
n8n (schedule, 5 min) → POST /ingest  → feeds (keyword gate, Google News link decode)
                                          → trafilatura → Postgres (articles)
                                       → embed locally + cluster near-duplicates (pgvector)
n8n (schedule, 5 min) → POST /classify → per-story structured LLM call (relevance, 4 themes,
                                          sentiment, priority, risk_score) → Postgres
                                       → risk_score ≥ 0.7 → alerts table
                                       → primary vendor down → fallback model (other vendor)
                                       → both vendors down → HTTP 503 → n8n Error Workflow
n8n (same 5-min run)  → GET /alerts/pending → for each: post to Slack (severity cue,
                                          headline, source, risk, reason, link) → POST /alerts/{id}/ack
n8n (schedule, 05:30 daily) → POST /brief → draft (LLM, cited) → verify (LLM,
                                          claim-by-claim against source) → Postgres
                                       → Slack send-and-wait: Approve / Disapprove (summary + signed link)
                                       → Approve (named)    → POST /approve → POST /deliver → DG office channel
                                       → Disapprove (named) → POST /disapprove → stop
                                       → no decision in 120 min → Slack @here + email to analyst team → stop
Analyst → n8n hosted chat (n8n login) → POST /ask → hybrid retrieval (BM25 + embeddings)
                                       → grounded answer + the articles it cites
```

Every LLM call goes through `app/services/llm.py`, which picks the vendor from the
model name (`claude-*` → Anthropic, `gemini-*` → Google, `humain-*` → HUMAIN Node,
otherwise OpenAI) and logs model, tokens and latency to the `runs` table.

## Model choice and cost

Two-tier model use: a small, cheap model for the high-volume per-story
classification step, and a stronger model for briefing generation and the claim
verifier (two calls a day). This spends compute only where reasoning quality matters
most — a briefing the Director General reads.

| Role | Model | Why |
|---|---|---|
| Classification | `gpt-6-luna` | Tied for best on the gold set at ~10x lower cost than the next option |
| Briefing + verifier | `gpt-6-sol` | Strong drafting; all claims verified on live runs |
| Classification fallback | `claude-haiku-4-5` | A different vendor on purpose; same cheap tier |
| Briefing fallback | `claude-sonnet-5-5` | A different vendor on purpose (see failure handling) |
| Embeddings | `multilingual-e5-large`, local | Arabic and English in one vector space; no text leaves the container |

**Measured cost** — from the `runs` table for this build (`make costs`), 29–30
September 2026, at the vendors' published standard rates on those dates:

- Classification on `gpt-6-luna`: **$0.268 per 1,000 articles** (412 production
  calls, average 1,379 input / 261 output tokens).
- One live daily briefing on `gpt-6-sol`, draft plus verification, 40 stories:
  **$0.10 and $0.12** on the two live runs. The same briefing served by the
  `claude-sonnet-5-5` fallback: $0.29.
- Embeddings and dedup run locally: $0 in API spend.
- Total LLM spend for the whole build session: **$4.52**, of which $3.85 was the
  model comparison (4 models × 120 items × 2 prompt versions) and $0.67 was the
  pipeline itself.

Projected run cost at the brief's ~1,500 items/day: classification ≈ **$12/month**
(45,000 × $0.268/1,000; this is an upper bound — 30% of live articles were
near-duplicates that are never sent to the model), briefings ≈ **$3.50/month**,
so **about $15/month**, or about $21 if every briefing fell back to the secondary
vendor. Not measured: the `/ask` endpoint (usage-dependent) and infrastructure.
Re-check vendor pricing before quoting these figures.

Model versions are pinned in `app/config.py`. The evaluation set is re-run
whenever a model version or prompt changes, since classifier calibration can
drift silently across model updates.

## Data handling and security

- **Public news only** in this prototype — acceptable to route through a hosted
  LLM API. OpenAI calls are sent with `store=False`, so responses are not retained
  on the vendor side for later retrieval; embeddings never leave the container.
- **Internal/confidential documents (production path, not built here):** would
  stay inside the client's environment — in-Kingdom or private model endpoint,
  no vendor training/retention — never sent to a general hosted API. The vendor
  routing in `llm.py` already supports an in-Kingdom option (HUMAIN Node); it is
  wired but untested pending preview access.
- **Access control at retrieval time:** production design attaches an ACL to
  every indexed chunk and filters in the retrieval query itself, not after
  generation, so a restricted document can't leak into an answer to an
  unauthorized user.
- **Prompt injection:** ingested article text is untrusted input. It is passed
  as data inside `<article>` tags, the classification/briefing steps have no
  tool access, output is schema-constrained, and the verifier double-checks
  claims — so a hostile phrase embedded in a scraped article can't hijack the
  pipeline's behavior.
- **Human sign-off is enforced technically, not just procedurally:** only a
  briefing with status=`approved` can be delivered; `/deliver` rejects anything
  else (including `disapproved`), and every endpoint except `/health` requires
  the shared API key. The key
  stands in for SSO: in production `approved_by` would come from the
  authenticated identity rather than a request field.
- **Audit trail:** `approved_by`, `approved_at`, the delivered `content_md` and the
  untouched AI draft (`draft_md`) are stored — traceable if a Director asks "who
  approved this," and the draft-vs-approved diff is the correction signal.
- **Synthetic fixtures never reach a real briefing:** excluded by default; only
  the offline demo opts in.
- Secrets via `.env` / a secrets manager in production, never committed. Database,
  API, n8n and Adminer ports are bound to localhost.

## Failure handling — the "06:45" story

1. Briefing generation is scheduled for 05:30, not 06:30, to leave ~75 minutes
   of recovery buffer before the 07:30 deadline.
2. Transient API errors (429, 5xx, connection) are retried with backoff by the
   vendor SDKs; malformed or truncated structured output is retried by
   `services/llm.py`.
3. If the primary briefing model still fails, the draft and the verifier each
   fall back to a secondary model at a **different vendor**. Tested on 30 September
   2026 by giving the pipeline an invalid OpenAI key: both steps failed over to
   `claude-sonnet-5-5` and produced a complete briefing (83 citations, 0 unverified
   claims) in 88 seconds. The `runs` table records the fallback.
4. If every model fails, a clearly labeled **DEGRADED** briefing is produced
   without any LLM: the classified stories ranked by risk, with a banner. The
   same happens when there is no classified coverage in the window.
5. If the verifier cannot run, the draft is marked as unverified rather than
   passed as clean (fail closed).
6. Classification — the alert path — uses the same failover through the same
   code (`call_structured_with_fallback`), to `claude-haiku-4-5`. Tested on 30
   September 2026 with an invalid OpenAI key: 12/12 stories classified by the
   fallback in 8.4 s, both known risk items still alerted, each row records the
   model that actually answered, and `/classify` reports `fallback_used` so n8n
   can see the system is running degraded. A per-batch circuit breaker sends the
   rest of a batch straight to the fallback after 3 primary failures, so an outage
   doesn't spend the 15-minute alert budget on retries. The fallback is weaker on
   the gold set (2 false alarms vs 1, theme F1 0.75 vs 0.82): degraded, not dark. Only if both vendors
   fail does `/classify` return 503, so the n8n Error Workflow pages on-call
   instead of alerts silently stopping (also tested). Overlapping scheduler runs
   are skipped with a Postgres advisory lock rather than double-processing.
7. Alert delivery is at-least-once: workflow 01 drains every pending alert each
   cycle, and acknowledges an alert only after its Slack post succeeds. A failed
   post leaves it pending for the next cycle (and fires the error workflow), so
   the worst case is a duplicate post, never a silently lost alert. That ack is a
   system acknowledgement (`acknowledged_by = "n8n: posted to Slack ..."`): it
   records delivery, not that a person read the alert. Measuring human response
   time against the 15-minute target needs a separate `notified_at`, leaving
   `/ack` for people.
8. A failing feed is isolated and reported per feed in the `/ingest` response.
9. Nothing reaches the Director General without a human-approved status,
   degraded or not. The approval fails closed, and the three outcomes are
   separated structurally in workflow 02, not by convention:
   - **Approve** (a captured, named Slack responder) is the only path wired to
     `/deliver` and the DG-office post.
   - **Disapprove** (named) calls `/disapprove`, which records who and when and
     sets status `disapproved` (never left as a dangling draft), then stops. No
     email: it is an explicit decision, already visible in the Slack thread.
   - **No decision** before the 120-minute wait expires (the Slack node then
     outputs its input, with no decision in it) or a click with no captured
     responder: an `@here` ping in the approvals channel and an email to
     `ANALYST_TEAM_EMAIL`, in parallel, saying which briefing is waiting, for how
     long, and linking to it. Neither branch can reach delivery; the API would
     refuse it anyway. The expired buttons cannot be used afterwards, so a
     decision then needs a fresh run of workflow 02.
10. Alert severity cue: each Slack alert starts with a red circle for
    risk_score >= 0.85 and an orange circle below that. It is a visual triage aid
    only, not a second alerting tier: every alert already cleared the single 0.70
    threshold, and the cue changes how an alert is displayed, never which items
    alert or who is notified.

## Evaluation methodology

A gold set of 120 items (`eval/gold_set.jsonl`: 104 live articles, 16 synthetic;
53 Arabic; 7 high-risk) is scored against the pipeline. Labels follow written rules
(`eval/LABELING_GUIDE.md`), were AI-drafted without sight of the pipeline's
predictions, and are under human review: **11 rows reviewed so far, 2 changed;
109 still unreviewed**, so the numbers below are provisional. `eval/run_eval.py`
reports alert recall/precision as the headline metric — missing a real crisis is
worse than a false alarm — plus relevance accuracy, multi-label theme F1 and
sentiment, sliced by language. `eval/compare_models.py` runs the production prompt
on several models side by side.

Results on the current prompt (30 September 2026; synthetic item #9 re-run 2 October after rewording):

| Model | Risk items caught | False alarms | Relevance | Theme F1 | $ / 1,000 |
|---|---|---|---|---|---|
| gpt-6-luna | 6/7 | 1 | 91% | 0.82 | 0.27 |
| gpt-6-sol | 6/7 | 1 | 91% | 0.84 | 4.85 |
| claude-haiku-4-5 | 6/7 | 2 | 87% | 0.75 | 2.77 |
| claude-sonnet-5-5 | 5/7 | 0 | 94% | 0.84 | 7.97 |

What the evaluation changed:
- **The alert policy belonged in the prompt.** The first prompt produced 3–10 false
  alarms per model, almost all war and political news, because nothing told the
  model the pager is for tourism-owned risk. Writing the policy into the rubric
  removed them; on live data, alerts on real coverage fell from 10 to 5.
- **Dedup threshold** raised from 0.88 to 0.90 after live pairs showed distinct
  stories merging below 0.90 (a false merge hides a story from the briefing).

Caveats, stated plainly:
- The prompt was revised after seeing errors on this same set, and there are only
  7 positives (each is worth 14 points of recall). A held-out set is needed.
- Arabic alert recall rests on a single, synthetic item.
- Scores vary between runs near the threshold: one article scored 0.82 in the
  eval and 0.55 when re-classified. A fixed 0.7 threshold is also not neutral
  across vendors, which calibrate differently.
- Synthetic fixtures were edited after seeing results: three to name the country
  they are set in, and (2 October) the coral-reef item #9, reworded from a
  hedged report ("could draw further scrutiny", already disputed, niche reach)
  into a clear current story, because it sat on the 0.70 alert line (primary
  model 4/5 runs alerting, fallback 0/5; after: 5/5 on both). Its gold label was
  always high-risk, but the rewording made it easier: Haiku and Sonnet each gained
  one caught item (5/7 -> 6/7 and 4/7 -> 5/7). The primary model's numbers did
  not change. Current-prompt outputs on the earlier wording are in git history
  (commit 0d08585); eval/results/prompt_v1 still holds old-prompt outputs on it.
  (3 October) The Arabic viral-video item #12 got the same country fix as the
  first three ("في المملكة", "in the Kingdom", added; nothing else changed): it
  never said where it happened, and the primary model judged it not relevant in
  2 of 5 runs (alerting 3/5; after: 5/5, 0.80-0.86). No eval number changed: the
  cached outputs it replaced had already caught it.
- Both current luna/sol errors are on `headline_only` articles, where the reviewer
  read the full source and the model saw only the headline (see next section).

Briefing faithfulness is checked by the claim-level verifier plus manual
spot-checks. Analyst corrections at approval time are the intended feedback loop
for improving the gold set and, over time, the prompts.

## What I'd build next with two more weeks

1. **Close the headline-only fetch gap — an ingestion fix, not a model fix.** 28% of
   live articles came from publishers that block automated fetches, so the pipeline
   kept only the headline. Both remaining classifier errors trace to this: a
   headline about a missile at Riyadh (#113) was scored not relevant, though the
   full story was the airport fuel-depot fire; and a headline about Cathay Pacific
   suspensions (#51) raised an alert, though the full story was a third extension of
   an existing suspension. No model can classify text it never received. Options:
   licensed feeds or a news API for the blocked outlets, polite retry through the
   publisher's own RSS body, and until then treating `headline_only` items as
   lower-confidence — routed to the analyst as "needs a read" rather than scored
   as if complete.
2. Finish the human review of the gold set, add a held-out set from the following
   days' coverage (with more real Arabic risk items), and an inter-annotator check.
3. A second pass for scores near the alert threshold to damp run-to-run
   variance, and per-model alert thresholds (the fallback calibrates differently).
4. Move access-control-at-retrieval from design to implementation, and pilot
   ingesting one internal document type under it on an in-Kingdom endpoint.
5. Shadow-mode run against the manual process to measure real agreement
   before cutover.
6. Cross-language retrieval for `/ask`. Measured on 1 October 2026: the same question
   about Riyadh airport disruptions found the answer in English and, asked in Arabic,
   replied that the coverage didn't mention it — keyword matching only finds Arabic
   articles and cross-language embedding scores rank below same-language ones. Fix:
   translate the question (one cheap LLM call) and retrieve in both languages.
7. Prompt-caching and batch-API use to reduce cost further at scale; LLM
   confirmation for cross-language duplicate pairs, which embeddings alone miss.
