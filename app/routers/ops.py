from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Alert, Article, Run

router = APIRouter()

# USD per 1M tokens (input, output), standard tier, uncached. Taken from the
# vendors' pricing pages on 2026-09-29 — re-verify before presenting numbers.
PRICES = {
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6-sol": (2.00, 10.00),
    "gpt-6-astra": (10.00, 50.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}


@router.get("/runs/summary")
def runs_summary(hours: int = 24, db: Session = Depends(get_db)):
    """Calls, failures, tokens, latency and estimated spend per step+model — the cost slide, live."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.execute(
        select(
            Run.step, Run.model, Run.status, func.count(),
            func.coalesce(func.sum(Run.input_tokens), 0), func.coalesce(func.sum(Run.output_tokens), 0),
            func.percentile_cont(0.5).within_group(Run.latency_ms),
        )
        .where(Run.started_at >= since)
        .group_by(Run.step, Run.model, Run.status)
    ).all()
    out, total = [], 0.0
    for step, model, status, n, tin, tout, p50 in rows:
        pin, pout = PRICES.get(model or "", (0.0, 0.0))
        cost = tin / 1e6 * pin + tout / 1e6 * pout
        total += cost
        out.append({"step": step, "model": model, "status": status, "calls": n, "input_tokens": tin,
                    "output_tokens": tout, "p50_latency_ms": p50, "est_cost_usd": round(cost, 4)})
    return {"window_hours": hours, "est_total_cost_usd": round(total, 4), "rows": out}


@router.get("/alerts/latency")
def alert_latency(db: Session = Depends(get_db)):
    """Time from publication / ingestion to alert — evidence for the 15-minute target."""
    rows = db.execute(
        select(
            func.extract("epoch", Alert.raised_at - Article.fetched_at),
            func.extract("epoch", Alert.raised_at - Article.published_at),
        ).join(Article, Article.id == Alert.article_id)
    ).all()

    def pct(vals: list[float], q: float) -> float | None:
        vals = sorted(vals)
        return round(vals[min(len(vals) - 1, int(q * len(vals)))] / 60, 1) if vals else None

    fetched = [float(r[0]) for r in rows if r[0] is not None]
    published = [float(r[1]) for r in rows if r[1] is not None]
    return {
        "alerts": len(rows),
        "ingest_to_alert_min": {"p50": pct(fetched, 0.5), "p95": pct(fetched, 0.95)},
        "publish_to_alert_min": {"p50": pct(published, 0.5), "p95": pct(published, 0.95)},
    }
