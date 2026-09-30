# Media Monitoring Agent — Consulum FDE Case Study

Agent that ingests news coverage, classifies it against four priority themes, drafts
a cited daily briefing for human approval, raises reputational-risk alerts within
15 minutes, and lets analysts query the archive in plain language.

## Run it (under 15 minutes)

```bash
git clone <this-repo> && cd media-monitor
cp .env.example .env        # add your ANTHROPIC_API_KEY
make up                      # builds and starts Postgres+pgvector, the API, and n8n
```

Then, either:
- **Automated (live feeds):** `make demo` runs ingest → classify → brief once, end to end, and prints the result.
- **Automated (guaranteed, no network dependency):** `make demo-safe` seeds a fixed
  set of synthetic backup articles (`eval/synthetic_articles.json`, clearly tagged
  `source="Synthetic Demo Data"`) — including deliberate high-risk items to trigger
  the alert path on command — then classifies and briefs. Use this as a fallback
  if a live feed is down during the actual presentation.
- **Via n8n:** open http://localhost:5678 (admin / changeme_local), import the workflows
  from `/n8n/*.json`, and trigger the Ingest workflow manually.
- **Browse the database directly:** http://localhost:8080 (Adminer) — System:
  PostgreSQL, Server: `db`, Username: `mm`, Password: `mm_local_password`,
  Database: `media_monitor`. Faster than writing psql queries while debugging.

To run the evaluation report against the hand-labeled gold set:
```bash
make eval
```

API docs (interactive): http://localhost:8000/docs

## What's built vs. what's deliberately scoped out

**Built:** ingest (8-10 English sources + Arabic Google News queries), URL-level +
embedding-based near-duplicate clustering, 4-theme classification with sentiment/
priority/risk score/justification, a cited briefing draft with a **claim-level
verifier** that checks every claim against its cited source, n8n approval workflow
(send-and-wait to a named analyst) and scheduled delivery, a 15-minute risk-alert
path, and a hybrid-retrieval (BM25 + embeddings) Q&A endpoint over the archive.

**Deliberately not built** (see architecture note for the intended design):
WhatsApp delivery, a polished front end, multi-user auth, ingestion of internal/
confidential documents. Cut to protect the reliability of the core loop within the
time box, per the brief's own guidance.

## Architecture

See `ARCHITECTURE.md` for the one-page note: component diagram, model choice and
cost rationale, security/data-handling design (including the path for internal
documents), the 06:45 failure-handling story, and the evaluation methodology.

## Repo layout

```
app/
  routers/        FastAPI endpoints — thin, call into services/
  services/        all real logic: ingestion, dedupe, embeddings, classification,
                    briefing + verification, retrieval, ask, alerting, LLM wrapper
  models.py         SQLAlchemy ORM (mirrors scripts/init_db.sql)
  schemas.py        Pydantic schemas — structured LLM output + API contracts
  sources.py        configured RSS/news feeds (swap freely, see comments)
eval/
  gold_set.jsonl    hand-labeled evaluation set (starter — expand to ~120 items)
  run_eval.py       precision/recall/F1 per theme + alert recall/precision
n8n/                exported workflow JSON: ingest, alert, briefing-approval, error
scripts/init_db.sql schema (articles, classifications, alerts, briefings, runs, gold_labels)
```

## Notes on data

Only public news sources / synthetic data used, per the brief's constraint. No
personal data or confidential material from any employer.
