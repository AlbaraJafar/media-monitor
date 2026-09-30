"""
Head-to-head model comparison on the gold set.

Runs the production classification prompt + schema with each candidate model on
every gold-labeled article, then prints one table: alert recall / precision,
relevance accuracy, theme macro-F1, sentiment accuracy, the Arabic slice, cost
per 1,000 articles, latency and failure rate. Nothing is written to the
production `classifications` / `alerts` tables — model outputs are cached in
eval/results/<model>.jsonl so re-running (e.g. after relabeling) costs nothing.
Delete a model's cache file to force a fresh run after a prompt change.

    docker compose exec api python -m eval.compare_models gpt-6-luna claude-haiku-4-5 gemini-3.1-flash-lite
"""
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sklearn.metrics import f1_score
from sklearn.preprocessing import MultiLabelBinarizer
from sqlalchemy import or_

from app.config import settings
from app.db import SessionLocal
from app.models import Article
from app.routers.ops import PRICES
from app.schemas import ClassificationResult
from app.services.classification import SYSTEM_PROMPT, _user_prompt
from app.services.llm import call_structured
from eval.run_eval import THEMES, load_gold

RESULTS_DIR = Path(__file__).parent / "results"


def _classify(model: str, article: Article) -> dict:
    db = SessionLocal()
    t0 = time.monotonic()
    try:
        r: ClassificationResult = call_structured(
            db=db, step=f"eval:{model}", model=model, system=SYSTEM_PROMPT,
            user_prompt=_user_prompt(article), schema=ClassificationResult,
            max_tokens=8000,  # headroom so models that think first aren't truncated into "failures"
        )
        out = {"ok": True, "relevant": r.relevant, "themes": [t.value for t in r.themes] if r.relevant else [],
               "sentiment": r.sentiment.value, "risk": r.risk_score if r.relevant else 0.0}
    except Exception as exc:
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        db.close()
    out["latency_ms"] = int((time.monotonic() - t0) * 1000)
    return out


def run_model(model: str, items: list[tuple[dict, Article]]) -> dict[str, dict]:
    RESULTS_DIR.mkdir(exist_ok=True)
    cache_path = RESULTS_DIR / f"{model}.jsonl"
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            cache[rec["url"]] = rec
    todo = [(g, a) for g, a in items if g["article_url"] not in cache]
    if todo:
        print(f"  {model}: classifying {len(todo)} articles ({len(items) - len(todo)} cached)...", flush=True)
        with ThreadPoolExecutor(max_workers=settings.classify_concurrency) as pool:
            results = list(pool.map(lambda ga: _classify(model, ga[1]), todo))
        with cache_path.open("a", encoding="utf-8") as f:
            for (g, _), res in zip(todo, results):
                rec = {"url": g["article_url"], **res}
                cache[rec["url"]] = rec
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return cache


def _tokens_for(model: str) -> tuple[int, int, int]:
    """Summed tokens + call count this model spent on eval runs (from the runs table)."""
    from sqlalchemy import func, select
    from app.models import Run
    db = SessionLocal()
    try:
        tin, tout, n = db.execute(
            select(func.coalesce(func.sum(Run.input_tokens), 0), func.coalesce(func.sum(Run.output_tokens), 0),
                   func.count()).where(Run.step == f"eval:{model}", Run.status == "ok")
        ).one()
        return int(tin), int(tout), int(n)
    finally:
        db.close()


def score(model: str, gold_items: list[tuple[dict, Article]], preds: dict[str, dict]) -> dict:
    rows = [(g, a, preds[g["article_url"]]) for g, a in gold_items if g["article_url"] in preds]
    ok = [(g, a, p) for g, a, p in rows if p["ok"]]
    thr = settings.risk_alert_threshold

    def alert_stats(subset):
        tp = sum(1 for g, _, p in subset if g["is_high_risk"] and p["risk"] >= thr)
        fn = sum(1 for g, _, p in subset if g["is_high_risk"] and p["risk"] < thr)
        fp = sum(1 for g, _, p in subset if not g["is_high_risk"] and p["risk"] >= thr)
        rec = tp / (tp + fn) if tp + fn else None
        prec = tp / (tp + fp) if tp + fp else None
        return rec, prec, fn, fp

    rec, prec, fn, fp = alert_stats(ok)
    ar_rec, _, _, _ = alert_stats([r for r in ok if (r[0].get("language") or r[1].language) == "ar"])

    rel = [(g, p) for g, _, p in ok if g["relevant"]]
    mlb = MultiLabelBinarizer(classes=THEMES)
    theme_f1 = f1_score(mlb.fit_transform([g["themes"] for g, _ in rel]),
                        mlb.transform([p["themes"] for _, p in rel]),
                        average="macro", zero_division=0) if rel else None

    tin, tout, calls = _tokens_for(model)
    price = PRICES.get(model)
    cost_per_1k = ((tin / calls) * price[0] + (tout / calls) * price[1]) / 1e6 * 1000 if price and calls else None
    lat = [p["latency_ms"] for _, _, p in ok]

    return {
        "model": model, "n": len(rows), "failures": len(rows) - len(ok),
        "alert_recall": rec, "alert_precision": prec, "missed": fn, "false_alarms": fp,
        "arabic_alert_recall": ar_rec,
        "relevance_acc": sum(g["relevant"] == p["relevant"] for g, _, p in ok) / len(ok) if ok else None,
        "theme_macro_f1": theme_f1,
        "sentiment_acc": (sum(g.get("sentiment") == p["sentiment"] for g, p in rel) / len(rel)) if rel else None,
        "cost_per_1k_articles_usd": cost_per_1k,
        "p50_latency_s": statistics.median(lat) / 1000 if lat else None,
    }


def main(models: list[str]) -> int:
    gold = load_gold()
    db = SessionLocal()
    items = []
    for g in gold:
        a = db.query(Article).filter(or_(Article.url == g["article_url"], Article.canonical_url == g["article_url"])).first()
        if a and a.clean_text:
            db.expunge(a)
            items.append((g, a))
    db.close()
    print(f"{len(items)}/{len(gold)} gold items found in the DB. Alert threshold {settings.risk_alert_threshold}.\n")

    results = [score(m, items, run_model(m, items)) for m in models]

    cols = [("model", "{}", 26), ("n", "{}", 4), ("failures", "{}", 8),
            ("alert_recall", "{:.0%}", 12), ("alert_precision", "{:.0%}", 15), ("missed", "{}", 6),
            ("false_alarms", "{}", 12), ("arabic_alert_recall", "{:.0%}", 19), ("relevance_acc", "{:.0%}", 13),
            ("theme_macro_f1", "{:.2f}", 14), ("sentiment_acc", "{:.0%}", 13),
            ("cost_per_1k_articles_usd", "${:.2f}", 24), ("p50_latency_s", "{:.1f}s", 13)]
    print("\n" + " ".join(name.ljust(w) for name, _, w in cols))
    for r in results:
        print(" ".join((fmt.format(r[name]) if r[name] is not None else "n/a").ljust(w) for name, fmt, w in cols))
    print("\nAlert recall is the headline: a missed crisis costs more than a false alarm. "
          "Treat differences of a few points on ~120 items as noise, not a ranking.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1:]))
