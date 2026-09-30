"""
Draft gold labels (AI-drafted per eval/LABELING_GUIDE.md, WITHOUT seeing pipeline
predictions) -> eval/gold_review.csv for human review.

After review, run `python -m eval.build_gold` to turn the reviewed CSV into
eval/gold_set.jsonl. This file is kept so the provenance of every draft label is
auditable: diff it against the reviewed CSV to see exactly what the human changed.

Theme codes: S = national_tourism_strategy_and_visitor_numbers
             G = destination_and_giga_project_launches
             A = aviation_visa_and_entry_policy
             R = reputational_risk_or_negative_coverage
Row format: article_id: (relevant, themes, sentiment, priority, is_high_risk, rationale)
"""
N, Y = False, True
NR = (N, "", "neutral", "low", N)  # not relevant

LABELS: dict[int, tuple] = {
    # ---- synthetic fixtures ----
    1: (Y, "S", "positive", "medium", N, "Q3 visitor record; flights/e-visa only mentioned as causes"),
    2: (Y, "A", "positive", "medium", N, "new direct route"),
    3: (Y, "G", "positive", "medium", N, "giga-project milestone"),
    4: (Y, "G,R", "negative", "medium", N, "second delay + analysts doubt target = negative coverage, but not a same-day response"),
    5: (Y, "A", "positive", "medium", N, "e-visa expansion"),
    6: (Y, "A,R", "negative", "medium", N, "advisory after complaints of 2h+ waits; visitor-facing negative, routine"),
    7: (Y, "R", "negative", "high", Y, "tourist safety incidents, no official response yet"),
    8: (Y, "R", "negative", "high", Y, "viral mistreatment video, intl outlet requesting comment"),
    9: (Y, "G,R", "negative", "high", Y, "prominent environmental criticism of flagship project before opening"),
    10: (Y, "S", "positive", "low", N, "domestic campaign results"),
    11: (Y, "S", "positive", "medium", N, "Arabic version of item 1"),
    12: (Y, "R", "negative", "high", Y, "Arabic version of item 8"),
    13: (Y, "A", "positive", "low", N, "charter/cargo approvals"),
    14: (Y, "G", "neutral", "low", N, "destination management (visitor cap); mild operator friction only"),
    15: (Y, "G", "positive", "low", N, "investment forum on giga-projects; neutral announcement is not R"),
    16: (Y, "S,R", "negative", "medium", N, "refund complaints + licence review; visitor-facing negative, not urgent"),
    # ---- English, live ----
    18: NR + ("climate diplomacy",),
    19: NR + ("foreign-policy meeting",),
    24: NR + ("labour market",),
    25: NR + ("e-government statistics",),
    26: NR + ("WHO candidacy",),
    27: (Y, "S", "positive", "low", N, "Hajj package for foreign pilgrims: visitor services for religious tourism"),
    29: NR + ("oil exports",),
    33: NR + ("UN / diplomacy",),
    34: NR + ("capital markets regulation",),
    36: NR + ("domestic speech",),
    42: NR + ("US-Iran geopolitics",),
    47: (Y, "R", "negative", "medium", N, "security disruption in the capital shapes safety perception; no visitor angle -> track, don't page"),
    51: (Y, "A,R", "negative", "medium", Y, "airline extends Riyadh suspensions for security reasons: flight disruption for visitors"),
    53: NR + ("border enforcement, not tourism",),
    54: NR + ("FMCG investment",),
    55: (Y, "G", "positive", "medium", N, "STA at Monaco Yacht Show: Red Sea yachting, AMAALA berths"),
    57: NR + ("PIF golf sponsorship abroad, no visitor angle",),
    59: (Y, "S", "positive", "low", N, "Ministry of Tourism / WEF initiative"),
    60: NR + ("sport sponsorship headline, no visitor angle",),
    61: (Y, "S", "positive", "medium", N, "STA x Wego destination campaign"),
    62: (Y, "A", "neutral", "low", N, "regional visa reform and routes incl. Gulf; borderline relevance"),
    63: (Y, "A", "positive", "low", N, "aviation market analysis"),
    64: (Y, "S", "positive", "low", N, "AI tourism vision / TourismX"),
    71: NR + ("FM on Gulf security at UNGA",),
    72: NR + ("military cooperation",),
    74: (Y, "S", "positive", "medium", N, "STA targeting Chinese visitors"),
    75: NR + ("Japan tourism body at ATM Dubai; not about Saudi tourism",),
    79: (Y, "A", "positive", "low", N, "helicopter operator supporting tourism"),
    80: (Y, "G", "positive", "medium", N, "Wadi Safar destination near Diriyah"),
    81: NR + ("women's football league (NEOM SC is a team)",),
    82: (Y, "G", "positive", "low", N, "AlUla cultural programme recognition"),
    87: (Y, "G", "positive", "low", N, "AlUla residency awards"),
    89: NR + ("'Neom' is a UK candle brand — keyword trap",),
    92: NR + ("AlUla basketball club — keyword trap",),
    93: (Y, "G", "positive", "medium", N, "AlUla responsible tourism gold award"),
    97: (Y, "G", "positive", "low", N, "hotel/mixed-use development pipeline"),
    98: (Y, "G", "positive", "low", N, "AlUla rock art heritage"),
    100: NR + ("sports site navigation page (extraction junk)",),
    103: NR + ("football match page",),
    104: NR + ("military threat to oil facilities",),
    106: (Y, "A,R", "negative", "high", Y, "'Is it safe to travel to Saudi?' + flight disruption: squarely visitor-facing"),
    108: (Y, "R", "negative", "medium", N, "same story as 47 (Jerusalem Post)"),
    110: NR + ("diplomatic visit",),
    112: (Y, "A", "positive", "medium", N, "Riyadh Air new Manchester route"),
    113: (Y, "R", "negative", "medium", N, "missile at the capital: destination safety perception; security news owned by others -> track"),
    114: (Y, "A,R", "negative", "high", Y, "attack with fire near Riyadh's main airport: aviation + visitor safety"),
    115: (Y, "R", "neutral", "medium", N, "fact-check debunking viral 'Riyadh airport burning' video; misinformation to track"),
    117: NR + ("geopolitical analysis",),
    123: (Y, "A", "positive", "medium", N, "Jeddah Terminal 4 opening"),
    125: NR + ("judicial case, no visitor angle",),
    192: NR + ("military strikes in Yemen",),
    195: (Y, "S", "neutral", "low", N, "GASTAT travel services trade data"),
    199: (Y, "G", "positive", "medium", N, "Red Sea Yacht Show announced"),
    # ---- Arabic, live ----
    127: (Y, "S", "positive", "medium", N, "tourism investment new phase, external marketing priority"),
    128: (Y, "S", "positive", "low", N, "op-ed on Saudi as global destination"),
    129: (Y, "S", "positive", "low", N, "luxury travel firm plans Saudi HQ"),
    130: (Y, "S", "positive", "low", N, "Saudi Winter season planning, Eastern Province"),
    131: (Y, "G", "positive", "medium", N, "Red Sea Global yacht network"),
    132: (Y, "S", "positive", "low", N, "GCC tourism GDP outlook; regional incl. KSA, borderline"),
    133: (Y, "S", "positive", "low", N, "national talent for cruise tourism"),
    134: (Y, "S", "positive", "low", N, "deputy emir meets deputy tourism minister"),
    135: (Y, "S", "positive", "medium", N, "KSA 29th in WEF travel & tourism index"),
    136: (Y, "G", "positive", "low", N, "first Saudi cruise ship (Aroya) inspected"),
    137: (Y, "S", "positive", "low", N, "tourism jobs improvement"),
    138: (Y, "S", "positive", "low", N, "experts on index ranking"),
    140: (Y, "G", "positive", "low", N, "Red Sea Authority coastal experience"),
    142: (Y, "S", "positive", "low", N, "HEADLINE AMBIGUOUS ('rich in its diversity'); relevance inferred from tourism query — reviewer check"),
    143: NR + ("South Korea tourism record",),
    144: (Y, "G", "positive", "low", N, "AlUla on global tourism map"),
    146: (Y, "S", "neutral", "medium", N, "new short-term rental licensing rules"),
    147: (Y, "S", "positive", "low", N, "op-ed: Al-Ahsa in Saudi tourism"),
    148: (Y, "S", "positive", "low", N, "tourism job demand, Eastern Province"),
    149: (Y, "S", "positive", "medium", N, "STA promotional visit to China"),
    152: NR + ("EU naval mission (Red Sea shipping)",),
    153: NR + ("EU naval mission explainer",),
    154: (Y, "G", "positive", "low", N, "Gulf Cup visitors and Jeddah entertainment options"),
    155: NR + ("Houthi air-defence analysis",),
    156: NR + ("routine weather forecast",),
    158: NR + ("Horn of Africa conflict",),
    159: NR + ("container shipping returns to Red Sea",),
    160: NR + ("oil exports",),
    161: NR + ("Egypt-Yemen diplomacy",),
    163: NR + ("EGYPT's Red Sea diving tourism — 'Red Sea' keyword trap",),
    165: NR + ("Yemeni minister on Houthi threats",),
    168: NR + ("EU naval deployment",),
    169: (Y, "G", "positive", "low", N, "Red Sea Museum, historic Jeddah"),
    171: NR + ("Houthi smuggling",),
    174: NR + ("contractor 'Red Sea International' (company, not the giga-project)",),
    177: NR + ("outbound travel to China",),
    178: (Y, "S,A", "neutral", "medium", N, "SAR 800k guarantee for visa-service tourism licences"),
    180: (Y, "R", "negative", "low", N, "hostile (Houthi-affiliated) outlet on Makkah; low reach -> track, don't page"),
    181: NR + ("outbound travel to Armenia",),
    183: NR + ("Egypt visa on arrival",),
    184: NR + ("food trade show exhibitors",),
    185: NR + ("Egypt (Siwa) tourism",),
    186: (Y, "R", "negative", "medium", N, "same story as 47 (schools remote in Riyadh)"),
    194: NR + ("Egyptian transport accident (Tourism Daily News is Egyptian)",),
    201: (Y, "G", "positive", "medium", N, "AlUla responsible tourism gold (Arabic)"),
    202: NR + ("oil loading at Yanbu",),
    203: (Y, "R", "neutral", "low", N, "AFP fact-check: old Jeddah video misattributed to escalation"),
    204: NR + ("Egyptian school tree-planting",),
    205: NR + ("Houthi-Shabaab alliance",),
    206: NR + ("Egyptian port cargo",),
    208: NR + ("Tunisia-Saudi trade",),
}

CODES = {"S": "national_tourism_strategy_and_visitor_numbers", "G": "destination_and_giga_project_launches",
         "A": "aviation_visa_and_entry_policy", "R": "reputational_risk_or_negative_coverage"}


def main() -> None:
    import csv
    from pathlib import Path

    from app.db import SessionLocal
    from app.models import Article

    db = SessionLocal()
    out = Path(__file__).parent / "gold_review.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:  # BOM so Excel renders Arabic
        w = csv.writer(f)
        w.writerow(["article_id", "language", "source", "title", "relevant", "themes", "sentiment", "priority",
                    "is_high_risk", "rationale", "reviewed_by", "changed_by_reviewer", "reviewer_note", "article_url"])
        for aid, (rel, themes, sent, prio, risk, why) in LABELS.items():
            a = db.get(Article, aid)
            w.writerow([aid, a.language, a.source, a.title, rel, themes, sent, prio, risk, why, "", "", "", a.url])
    db.close()
    n_risk = sum(1 for v in LABELS.values() if v[4])
    n_rel = sum(1 for v in LABELS.values() if v[0])
    print(f"wrote {out} — {len(LABELS)} rows, {n_rel} relevant, {n_risk} high-risk")


if __name__ == "__main__":
    main()
