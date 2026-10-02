"""
Seed the DB with synthetic backup articles (eval/synthetic_articles.json).

Use this if live feed sources are unreliable on demo day, or to guarantee
at least a few deliberate high-risk items exist to trigger the alert path
on command during the live demo. These are clearly tagged
source="Synthetic Demo Data" so you can point at them honestly in the
presentation rather than passing them off as real coverage.

    docker compose exec api python -m scripts.seed_synthetic           # insert missing ones
    docker compose exec api python -m scripts.seed_synthetic --reset   # re-arm for a demo

--reset is what `make demo-safe` uses. Without it, a second run on a later day
does nothing useful: the articles already exist (so nothing is inserted), are
already classified (so nothing is classified), and were fetched days ago (so
they fall outside the 24h briefing window). --reset makes them "just arrived":
fresh timestamps, and their old classifications and alerts removed, so the
demo shows classification, alerting and briefing happening live every time.
Only rows with source="Synthetic Demo Data" are touched.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import Alert, Article, Classification
from app.services.dedupe import run_dedupe

DATA_PATH = Path(__file__).parent.parent / "eval" / "synthetic_articles.json"
SYNTHETIC_SOURCE = "Synthetic Demo Data"


def main(reset: bool = False) -> None:
    with open(DATA_PATH, encoding="utf-8") as f:
        items = json.load(f)

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    inserted = skipped = 0

    for item in items:
        exists = db.query(Article.id).filter(Article.url == item["url"]).first()
        if exists:
            skipped += 1
            continue

        db.add(Article(
            source=item["source"],
            url=item["url"],
            canonical_url=item["url"],
            title=item["title"],
            language=item.get("language"),
            published_at=now,
            fetched_at=now,
            clean_text=item["clean_text"],
            is_canonical=True,
        ))
        inserted += 1
    db.commit()

    rearmed = cleared_cls = cleared_alerts = 0
    if reset:
        ids = db.execute(select(Article.id).where(Article.source == SYNTHETIC_SOURCE)).scalars().all()
        if ids:
            cleared_alerts = db.execute(delete(Alert).where(Alert.article_id.in_(ids))).rowcount
            cleared_cls = db.execute(delete(Classification).where(Classification.article_id.in_(ids))).rowcount
            for a in db.execute(select(Article).where(Article.id.in_(ids))).scalars():
                a.fetched_at = a.published_at = now
            rearmed = len(ids)
            db.commit()

    # Same embed + cluster step /ingest runs, so /ask and the briefing's
    # "also covered by" work on the synthetic path too.
    dedupe = run_dedupe(db)
    db.close()
    print(f"Seeded {inserted} synthetic articles ({skipped} already present). Dedupe: {dedupe}")
    if reset:
        print(f"Re-armed {rearmed} synthetic articles: timestamps set to now, "
              f"{cleared_cls} classification rows and {cleared_alerts} alerts cleared.")
    print("Run `make classify` next, then `make brief-synthetic` to see them flow through the pipeline.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--reset", action="store_true",
                        help="re-arm existing synthetic articles for a fresh demo run")
    main(reset=parser.parse_args().reset)
