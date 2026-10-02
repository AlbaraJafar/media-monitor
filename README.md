# Media Monitoring Agent

Agent that ingests news coverage, classifies it against four priority themes, drafts
a cited daily briefing for human approval, raises reputational-risk alerts within
15 minutes, and lets analysts query the archive in plain language.

## Run it (under 15 minutes)

```bash
git clone <this-repo> && cd media-monitor
cp .env.example .env        # add OPENAI_API_KEY (and ANTHROPIC_API_KEY for the fallback), set API_KEY
make up                      # builds and starts Postgres+pgvector, the API, n8n and Adminer
```

First boot downloads the local embedding model (~2 GB, cached in a Docker volume);
`GET /health` reports `embedder_loaded: true` when it is ready. On Windows, install
`make` with `winget install ezwinports.make`, or run the commands in the Makefile directly.

Then, either:
- **Automated (live feeds):** `make demo` runs ingest → classify → alerts → brief once,
  end to end, on real coverage. Synthetic fixtures are never included in this briefing.
- **Automated (guaranteed, no network dependency):** `make demo-safe` seeds a fixed
  set of synthetic backup articles (`eval/synthetic_articles.json`, clearly tagged
  `source="Synthetic Demo Data"`) — including deliberate high-risk items to trigger
  the alert path on command — then classifies and briefs. Real reputational-risk
  coverage is rare in any given window, so this is the only way to show the alert
  path firing on demand, and the fallback if a live feed is down during the presentation.
- **Via n8n:** open http://localhost:5678 (create the owner account on first visit —
  n8n no longer has a default login). Import the four workflows, either in the UI from
  `/n8n/*.json` or from the CLI (each file has a fixed id, so re-importing updates
  rather than duplicates):
  ```bash
  docker compose exec n8n n8n import:workflow --input=/workflows/03-error-workflow.json
  ```
  | Workflow | What it does |
  |---|---|
  | 01 - Ingest and Classify | every 5 min (or *Run Now*): `/ingest` → `/classify` → post each pending risk alert to Slack → `/alerts/{id}/ack` |
  | 02 - Briefing Approval and Delivery | 05:30: draft → Slack approval by a named analyst → `/approve` → `/deliver` → post the approved briefing to the DG office channel |
  | 03 - Error Workflow | pages on-call in Slack when 01, 02 or 04 fails |
  | 04 - Analyst Q&A | chat over the archive (see below) |

  The Slack messages carry a length-bounded summary plus a signed, expiring link to
  the full briefing (`/brief/{id}/view/...`), because Slack rejects blocks over 3,000
  characters. Select your Slack credential on the Slack nodes after a fresh import,
  and invite the Slack app to both channels.
- **Ask the archive in plain language (n8n chat):** activate *04 - Analyst Q&A* and
  open the chat URL shown on its *Analyst Chat* node (sign in with your n8n account).
  Each question goes to `POST /ask` (hybrid BM25 + embedding retrieval over the
  archive, answer grounded only in retrieved articles), and the reply lists the
  articles the answer cites, with links. It says so when nothing relevant was found
  rather than guessing. Known limitation: retrieval favours articles in the
  question's own language, so an Arabic question can miss coverage that exists only
  in English (and vice versa) — ask in the language the coverage is likely in.
- **Browse the database directly:** http://localhost:8080 (Adminer) — System:
  PostgreSQL, Server: `db`, Username: `mm`, Password: `mm_local_password`,
  Database: `media_monitor`. A local debugging convenience, bound to localhost only;
  it would not ship to production.

API docs (interactive): http://localhost:8000/docs — click **Authorize** and paste
`API_KEY` from `.env`. Every endpoint except `/health` requires it.

Useful extras: `make costs` (measured LLM spend per step and model), `make latency`
(publish → alert timing), `make alerts`, `make reset`.

## Evaluation

```bash
make eval                                                     # score what the pipeline stored
docker compose exec api python -m eval.compare_models gpt-6-luna claude-haiku-4-5   # head-to-head
```

The gold set (`eval/gold_set.jsonl`, 120 items, 53 Arabic) is built from
`eval/gold_review.csv` by `python -m eval.build_gold`, following the written rules in
`eval/LABELING_GUIDE.md`. Labels were AI-drafted without sight of the pipeline's
predictions and are being human-reviewed; each row records its provenance, and
`build_gold` warns about rows not yet reviewed. See ARCHITECTURE.md for results and
their caveats.

## What's built vs. what's deliberately scoped out

**Built:** ingest (6 outlet feeds + 8 Google News queries, English and Arabic, with
Google News links resolved to the real publisher), URL-level + embedding-based
near-duplicate clustering, 4-theme classification with relevance gate, sentiment,
priority, risk score and justification (schema-enforced structured output), a cited
briefing draft with a **claim-level verifier** that checks every claim against its
cited source and fails closed, a tested **cross-vendor model fallback** on both the
alert path and the briefing, and a no-LLM DEGRADED briefing, n8n approval workflow
(send-and-wait to a named analyst, approver recorded) and delivery of the approved
briefing to the DG office Slack channel, a 15-minute risk-alert path, a
hybrid-retrieval (BM25 + embeddings) Q&A endpoint with an n8n chat front end,
per-call cost/latency logging, and an evaluation harness that compares models side
by side.

**Deliberately not built** (see architecture note for the intended design):
WhatsApp delivery, a polished front end, multi-user auth (a shared API key stands in
for SSO), ingestion of internal/confidential documents. Cut to protect the
reliability of the core loop within the time box, per the brief's own guidance.

## Measured cost

From this build's own `runs` table (`make costs`), not an estimate:

| Step | Model | Measured |
|---|---|---|
| Classification | gpt-6-luna | **$0.268 per 1,000 articles** (412 calls, avg 1,379 in / 261 out tokens) |
| Daily briefing (draft + verify, 40 stories) | gpt-6-sol | **$0.10–0.12 each** |
| Same briefing served by the fallback | claude-sonnet-5-5 | $0.29 |
| Embeddings / dedup | local e5 model | $0 |

At the brief's ~1,500 items/day that is **about $12/month for classification plus
$3.50 for briefings — roughly $15/month**. Details and assumptions in ARCHITECTURE.md.

## Architecture

See `ARCHITECTURE.md` for the one-page note: component diagram, model choice and
measured cost, security/data-handling design (including the path for internal
documents), the 06:45 failure-handling story and the failover test, and the
evaluation methodology and results.

## Repo layout

```
app/
  routers/        FastAPI endpoints — thin, call into services/ (ops.py = cost + latency)
  services/        all real logic: ingestion, dedupe, embeddings, classification,
                    briefing + verification, retrieval, ask, alerting, LLM wrapper
  services/llm.py   the only file that knows which vendor is behind a model name
  security.py       API-key check for every non-health endpoint
  models.py         SQLAlchemy ORM (mirrors scripts/init_db.sql)
  schemas.py        Pydantic schemas — structured LLM output + API contracts
  sources.py        configured feeds and the keyword gate (verified 2026-09-29)
eval/
  LABELING_GUIDE.md what "correct" means, including the alert policy
  gold_review.csv   labels under human review  ->  build_gold.py  ->  gold_set.jsonl
  run_eval.py       alert recall/precision, relevance, multi-label theme F1, by language
  compare_models.py same prompt, several models: quality, cost, latency side by side
  synthetic_articles.json   demo fixtures
n8n/                workflow JSON: 01 ingest+alert, 02 briefing approval+delivery, 03 error, 04 analyst Q&A chat
scripts/init_db.sql schema (articles, classifications, alerts, briefings, runs, gold_labels)
```

## Notes on data

Only public news sources / synthetic data used, per the brief's constraint. No
personal data or confidential material from any employer.
