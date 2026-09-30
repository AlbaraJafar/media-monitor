"""
Evaluation harness.

Loads eval/gold_set.jsonl (hand-labeled articles), matches each labeled URL
against what the pipeline actually stored in `classifications`, and prints:
  - alert recall/precision — the headline metric (did we catch the risky ones,
    without crying wolf on everything), with every miss listed by title
  - relevance gate accuracy (off-topic items correctly rejected)
  - per-theme precision/recall/F1, scored as MULTI-LABEL (an article can
    legitimately be both a giga-project story and a reputational risk)
  - sentiment accuracy
  - all of the above sliced by language, since Arabic is where a
    multilingual pipeline usually quietly underperforms

Gold line format (one JSON object per line):
  {"article_url": "...", "title": "...", "language": "en|ar", "relevant": true,
   "themes": ["reputational_risk_or_negative_coverage", ...], "sentiment": "negative",
   "priority": "high", "is_high_risk": true, "notes": "why this label"}
Legacy lines with a single "theme" string are still accepted.

Run inside the api container so it shares the DB connection:
    docker compose exec api python -m eval.run_eval
"""
import json
import sys
from collections import Counter
from pathlib import Path

from sklearn.metrics import classification_report
from sklearn.preprocessing import MultiLabelBinarizer
from sqlalchemy import or_

from app.config import settings
from app.db import SessionLocal
from app.models import Article, Classification
from app.schemas import Theme
from app.services.classification import NOT_RELEVANT

GOLD_PATH = Path(__file__).parent / "gold_set.jsonl"
THEMES = [t.value for t in Theme]


def load_gold() -> list[dict]:
    rows = []
    with open(GOLD_PATH, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            item = json.loads(line)
            if "themes" not in item:
                item["themes"] = [item["theme"]] if item.get("theme") else []
            item.setdefault("relevant", bool(item["themes"]))
            item["_line"] = n
            rows.append(item)
    return rows


def predictions_for(db, url: str) -> tuple[Article | None, list[Classification]]:
    article = db.query(Article).filter(or_(Article.url == url, Article.canonical_url == url)).first()
    if not article:
        return None, []
    preds = db.query(Classification).filter(Classification.article_id == article.id).all()
    if not preds and article.cluster_id and article.cluster_id != article.id:
        # near-duplicate: the pipeline only classifies the cluster head, and the
        # duplicate inherits that label — so that's the prediction to score
        preds = db.query(Classification).filter(Classification.article_id == article.cluster_id).all()
    return article, preds


def pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def report(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    print(f"\n{'=' * 70}\n{name}  (n={len(rows)})\n{'=' * 70}")

    # --- Alerts (headline) ---
    tp = [r for r in rows if r["gold_risk"] and r["pred_risk"]]
    fn = [r for r in rows if r["gold_risk"] and not r["pred_risk"]]
    fp = [r for r in rows if not r["gold_risk"] and r["pred_risk"]]
    recall = len(tp) / (len(tp) + len(fn)) if tp or fn else float("nan")
    precision = len(tp) / (len(tp) + len(fp)) if tp or fp else float("nan")
    print(f"\nALERTS (threshold {settings.risk_alert_threshold})")
    print(f"  recall    {pct(recall)}   ({len(tp)}/{len(tp) + len(fn)} real risks caught)")
    print(f"  precision {pct(precision)}   ({len(fp)} false alarms)")
    for r in fn:
        print(f"  MISSED  risk={r['score']:.2f}  {r['title'][:80]}")
    for r in fp:
        print(f"  FALSE   risk={r['score']:.2f}  {r['title'][:80]}")

    # --- Relevance gate ---
    rel_correct = sum(r["gold_relevant"] == r["pred_relevant"] for r in rows)
    rejected_wrongly = [r for r in rows if r["gold_relevant"] and not r["pred_relevant"]]
    print(f"\nRELEVANCE  accuracy {pct(rel_correct / len(rows))}  "
          f"(gold off-topic: {sum(not r['gold_relevant'] for r in rows)}, "
          f"relevant items wrongly rejected: {len(rejected_wrongly)})")
    for r in rejected_wrongly:
        print(f"  REJECTED  {r['title'][:80]}")

    # --- Themes (multi-label, relevant gold items only) ---
    rel = [r for r in rows if r["gold_relevant"]]
    if rel:
        mlb = MultiLabelBinarizer(classes=THEMES)
        y_true = mlb.fit_transform([r["gold_themes"] for r in rel])
        y_pred = mlb.transform([[t for t in r["pred_themes"] if t in THEMES] for r in rel])
        print("\nTHEMES (multi-label; support = gold items carrying the theme)")
        print(classification_report(y_true, y_pred, target_names=THEMES, zero_division=0))
        exact = sum(set(r["gold_themes"]) == set(r["pred_themes"]) for r in rel)
        print(f"  exact theme-set match: {pct(exact / len(rel))}")

    # --- Sentiment ---
    sent = [r for r in rows if r["gold_relevant"] and r["gold_sentiment"]]
    if sent:
        acc = sum(r["gold_sentiment"] == r["pred_sentiment"] for r in sent) / len(sent)
        confusions = Counter((r["gold_sentiment"], r["pred_sentiment"]) for r in sent
                             if r["gold_sentiment"] != r["pred_sentiment"])
        print(f"\nSENTIMENT  accuracy {pct(acc)}  confusions (gold->pred): {dict(confusions)}")


def main() -> int:
    gold = load_gold()
    if not gold:
        print("No gold labels found — see eval/gold_set.jsonl")
        return 1

    db = SessionLocal()
    rows, missing = [], []
    for item in gold:
        article, preds = predictions_for(db, item["article_url"])
        if not preds:
            missing.append((item["_line"], item.get("title") or item["article_url"],
                            "not ingested" if not article else "not classified"))
            continue
        pred_themes = sorted({p.theme for p in preds} - {NOT_RELEVANT})
        score = max(float(p.risk_score) for p in preds)
        rows.append({
            "title": item.get("title") or article.title,
            "language": item.get("language") or article.language or "?",
            "synthetic": article.source == "Synthetic Demo Data",
            "gold_relevant": item["relevant"],
            "pred_relevant": bool(pred_themes),
            "gold_themes": item["themes"],
            "pred_themes": pred_themes,
            "gold_sentiment": item.get("sentiment"),
            "pred_sentiment": preds[0].sentiment,
            "gold_risk": bool(item["is_high_risk"]),
            "pred_risk": score >= settings.risk_alert_threshold,
            "score": score,
        })
    db.close()

    print(f"\nMatched {len(rows)}/{len(gold)} gold items to pipeline output "
          f"(classify model: {settings.classify_model}).")
    if missing:
        print(f"{len(missing)} gold items have no prediction — run ingest/seed + classify, or fix URLs:")
        for line, title, why in missing[:15]:
            print(f"  line {line}: {why}: {title[:70]}")

    report("ALL ITEMS", rows)
    for lang in sorted({r["language"] for r in rows}):
        report(f"LANGUAGE = {lang}", [r for r in rows if r["language"] == lang])
    report("REAL COVERAGE ONLY (excl. synthetic)", [r for r in rows if not r["synthetic"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
