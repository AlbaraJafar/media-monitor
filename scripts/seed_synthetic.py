"""
Seed the DB with synthetic backup articles (eval/synthetic_articles.json).

Use this if live feed sources are unreliable on demo day, or to guarantee
at least a few deliberate high-risk items exist to trigger the alert path
on command during the live demo. These are clearly tagged
source="Synthetic Demo Data" so you can point at them honestly in the
presentation rather than passing them off as real coverage.

Run inside the api container:
    docker compose exec api python -m scripts.seed_synthetic
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.db import SessionLocal
from app.models import Article
from app.services.dedupe import run_dedupe

DATA_PATH = Path(__file__).parent.parent / "eval" / "synthetic_articles.json"


def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        items = json.load(f)

    db = SessionLocal()
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
            published_at=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            clean_text=item["clean_text"],
            is_canonical=True,
        ))
        inserted += 1

    db.commit()
    # Same embed + cluster step /ingest runs, so /ask and the briefing's
    # "also covered by" work on the synthetic path too.
    dedupe = run_dedupe(db)
    db.close()
    print(f"Seeded {inserted} synthetic articles ({skipped} already present). Dedupe: {dedupe}")
    print("Run `make classify` next, then `make brief` to see them flow through the pipeline.")


if __name__ == "__main__":
    main()
