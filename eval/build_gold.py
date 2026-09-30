"""
eval/gold_review.csv (human-reviewed) -> eval/gold_set.jsonl (what the evals read).

A row counts as human-reviewed only when `reviewed_by` is filled in; until
then its provenance stays "ai_draft_unreviewed". Validates every row against the labeling guide's vocabulary so a typo in Excel
can't silently become a wrong label, and reports how many rows the reviewer
changed — report that number next to the metrics.

    docker compose exec api python -m eval.build_gold
"""
import csv
import json
import sys
from pathlib import Path

from eval.draft_labels import CODES

HERE = Path(__file__).parent
TRUE = {"true", "yes", "1", "y"}
FALSE = {"false", "no", "0", "n", ""}


def _bool(v: str, field: str, row: int) -> bool:
    v = v.strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    raise ValueError(f"row {row}: {field}={v!r} is not true/false")


def main() -> int:
    rows, errors, changed, unreviewed = [], [], 0, 0
    with (HERE / "gold_review.csv").open(encoding="utf-8-sig", newline="") as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            try:
                relevant = _bool(r["relevant"], "relevant", n)
                codes = [c.strip().upper() for c in r["themes"].replace(";", ",").split(",") if c.strip()]
                bad = [c for c in codes if c not in CODES]
                if bad:
                    raise ValueError(f"row {n}: unknown theme code(s) {bad}; use S/G/A/R")
                if relevant != bool(codes):
                    raise ValueError(f"row {n}: relevant={relevant} but themes={codes or 'none'}")
                if r["sentiment"] not in ("positive", "neutral", "negative"):
                    raise ValueError(f"row {n}: sentiment={r['sentiment']!r}")
                if r["priority"] not in ("low", "medium", "high"):
                    raise ValueError(f"row {n}: priority={r['priority']!r}")
                high_risk = _bool(r["is_high_risk"], "is_high_risk", n)
                if high_risk and not relevant:
                    raise ValueError(f"row {n}: high-risk items must be relevant")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            reviewer = (r.get("reviewed_by") or "").strip()
            was_changed = _bool(r.get("changed_by_reviewer", ""), "changed_by_reviewer", n)
            changed += was_changed
            unreviewed += not reviewer
            provenance = ("ai_draft_unreviewed" if not reviewer
                          else f"ai_draft_changed_by:{reviewer}" if was_changed
                          else f"ai_draft_confirmed_by:{reviewer}")
            rows.append({
                "article_url": r["article_url"], "title": r["title"], "language": r["language"],
                "relevant": relevant, "themes": [CODES[c] for c in codes], "sentiment": r["sentiment"],
                "priority": r["priority"], "is_high_risk": high_risk,
                "notes": r["rationale"] + (f" | reviewer: {r['reviewer_note']}" if r.get("reviewer_note") else ""),
                "label_provenance": provenance,
            })

    if errors:
        print("Fix these rows in gold_review.csv, then re-run:\n  " + "\n  ".join(errors))
        return 1
    with (HERE / "gold_set.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote gold_set.jsonl: {len(rows)} items, {sum(r['is_high_risk'] for r in rows)} high-risk, "
          f"{sum(r['language'] == 'ar' for r in rows)} Arabic; reviewer changed {changed} rows.")
    if unreviewed:
        print(f"WARNING: {unreviewed} rows have no reviewed_by — these are still AI-drafted labels. "
              "Don't present metrics as 'hand-labeled' until every row is reviewed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
