# Source list for ingestion. Every URL below was verified to resolve and return
# entries on 2026-09-28/29. Re-check before a demo: outlets move their feeds.
# Arab News' direct feed intermittently 403s automated clients; kept because
# failures are isolated per feed and reported in the /ingest response, and its
# stories also arrive via the Google News queries.
#
# Two kinds of source:
#   - Topic-scoped Google News queries (English + Arabic). High precision, and the
#     only reliable route to Arabic coverage (SPA, Okaz and Sabq feeds were empty or
#     403 to automated clients). Links are Google redirect stubs; ingestion decodes
#     them to the real publisher URL and records the real publisher as `source`.
#   - Direct outlet feeds. Broad, mostly off-topic (general regional news), so they
#     pass a cheap keyword gate (`keyword_filter`) before we spend a fetch or an LLM
#     call on them.
#
# Dropped/replaced during verification: saudigazette.com.sa/rssFeed/1 (empty),
# gulfnews.com/rss (404), thenationalnews.com/rss (404), zawya/travelweekly/
# alarabiya English (403 to bots).

def _gn(query: str, lang: str) -> str:
    from urllib.parse import quote_plus
    if lang == "ar":
        return f"https://news.google.com/rss/search?q={quote_plus(query)}+when:3d&hl=ar&gl=SA&ceid=SA:ar"
    return f"https://news.google.com/rss/search?q={quote_plus(query)}+when:3d&hl=en-US&gl=US&ceid=US:en"


SOURCES: list[dict] = [
    # --- Direct outlet feeds (keyword-gated) ---
    {"name": "Arab News", "url": "https://www.arabnews.com/rss.xml", "lang": "en", "keyword_filter": True},
    {"name": "Saudi Gazette", "url": "https://saudigazette.com.sa/rssFeed/74", "lang": "en", "keyword_filter": True},
    {"name": "Gulf News", "url": "https://gulfnews.com/feed", "lang": "en", "keyword_filter": True},
    {"name": "The National", "url": "https://www.thenationalnews.com/arc/outboundfeeds/rss/?outputType=xml", "lang": "en", "keyword_filter": True},
    {"name": "Arabian Business", "url": "https://www.arabianbusiness.com/feed", "lang": "en", "keyword_filter": True},
    {"name": "Skift", "url": "https://www.skift.com/feed/", "lang": "en", "keyword_filter": True},
    {"name": "Simple Flying", "url": "https://simpleflying.com/feed/", "lang": "en", "keyword_filter": True},

    # --- Topic-scoped Google News queries (English), last 3 days ---
    {"name": "Google News", "url": _gn("Saudi tourism", "en"), "lang": "en"},
    {"name": "Google News", "url": _gn("NEOM OR Qiddiya OR \"Red Sea Global\" OR Diriyah OR AlUla", "en"), "lang": "en"},
    {"name": "Google News", "url": _gn("Saudi visa OR Saudi airline OR Riyadh Air OR Saudi airport", "en"), "lang": "en"},
    # Risk query. Google News reads "a b OR c OR d" as an over-constrained AND chain
    # (the original version of this query returned 0 results); grouping fixes it.
    # Expect mostly noise here: real reputational stories are rare in any 3-day
    # window, and the classifier's relevance flag + risk score does the filtering.
    {"name": "Google News", "url": _gn('Saudi (tourists OR tourism OR NEOM OR "Red Sea" OR AlUla) '
                                       '(criticism OR controversy OR complaint OR scam OR boycott OR accident OR "human rights")', "en"), "lang": "en"},

    # --- Arabic ---
    {"name": "Google News", "url": _gn("السياحة السعودية", "ar"), "lang": "ar"},
    {"name": "Google News", "url": _gn("نيوم OR القدية OR البحر الأحمر OR الدرعية OR العلا", "ar"), "lang": "ar"},
    {"name": "Google News", "url": _gn("التأشيرة السياحية السعودية OR الطيران السعودي", "ar"), "lang": "ar"},
    {"name": "Google News", "url": _gn("السياحة السعودية (انتقادات OR شكاوى OR حادث OR احتيال)", "ar"), "lang": "ar"},
]

# Keyword gate for general outlet feeds, matched case-insensitively against
# title + RSS summary. Deliberately broad: its job is to drop Guinea-Bissau
# election stories, not to classify. Recall of the gate itself is spot-checked
# in the eval (off-topic items that *should* have passed would show up as misses).
RELEVANCE_KEYWORDS: list[str] = [
    "saudi", "ksa", "riyadh", "jeddah", "mecca", "makkah", "medina", "madinah",
    "dammam", "abha", "taif", "neom", "red sea", "qiddiya", "diriyah", "alula", "al-ula",
    "trojena", "sindalah", "amaala", "hajj", "umrah", "vision 2030", "pif",
    "riyadh air", "saudia", "flynas", "flyadeal", "e-visa", "evisa",
    "السعودية", "السياحة", "الرياض", "جدة", "نيوم", "العلا", "الدرعية", "القدية", "تأشيرة",
]
