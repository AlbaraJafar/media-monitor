import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit, urlunsplit

import feedparser
import httpx
import trafilatura
from langdetect import LangDetectException, detect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Article
from app.sources import RELEVANCE_KEYWORDS, SOURCES

logger = logging.getLogger("ingestion")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_MIN_ARTICLE_CHARS = 300  # below this, extraction almost certainly got a paywall/consent page

# Tracking params etc. stripped so the same story isn't stored twice
# under two URLs that only differ by query string.
_STRIP_QUERY_PREFIXES = ("utm_", "ref", "fbclid", "gclid")

_KEYWORD_RE = re.compile(
    "|".join(rf"\b{re.escape(k)}\b" if k.isascii() else re.escape(k) for k in RELEVANCE_KEYWORDS),
    re.IGNORECASE,
)


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    kept = [
        kv
        for kv in parts.query.split("&")
        if kv and not any(kv.lower().startswith(p) for p in _STRIP_QUERY_PREFIXES)
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "&".join(kept), ""))


def detect_language(text: str) -> str | None:
    if not text or len(text.strip()) < 20:
        return None
    try:
        return detect(text)
    except LangDetectException:
        return None


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def fetch_feed_entries(client: httpx.Client, feed_url: str) -> list:
    # Fetch with our own client (timeouts, UA) — feedparser's built-in fetch has no timeout.
    resp = client.get(feed_url)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.bozo_exception}")
    return parsed.entries


def decode_google_news_url(client: httpx.Client, link: str) -> str | None:
    """
    Google News RSS links are JS-redirect stubs (news.google.com/rss/articles/<id>),
    not HTTP redirects, so a plain GET never reaches the publisher. Resolve the real
    URL the same way the Google News web client does: read the signature/timestamp
    off the article page, then ask the batchexecute endpoint for the target URL.
    Unofficial and may break if Google changes it — failures fall back to headline-only.
    """
    art_id = urlsplit(link).path.rsplit("/", 1)[-1]
    page = client.get(f"https://news.google.com/articles/{art_id}")
    sg = re.search(r'data-n-a-sg="([^"]+)"', page.text)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page.text)
    if not (sg and ts):
        return None
    inner = (
        '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
        f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{art_id}",{ts.group(1)},"{sg.group(1)}"]'
    )
    resp = client.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        content=f"f.req={quote(json.dumps([[['Fbv4je', inner]]]))}",
    )
    payload = json.loads(resp.text.split("\n\n", 1)[1])[:-2]
    return json.loads(payload[0][2])[1]


def extract_article_text(client: httpx.Client, url: str) -> tuple[str, str | None]:
    """Returns (final_url, clean_text or None)."""
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("article fetch failed for %s: %s", url, exc)
        return url, None
    clean = trafilatura.extract(resp.text, favor_recall=True)
    if not clean or len(clean) < _MIN_ARTICLE_CHARS:
        return str(resp.url), None
    return str(resp.url), clean


def _entry_published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*parsed[:6], tzinfo=timezone.utc) if parsed else None


def _process_entry(feed: dict, entry) -> dict | None:
    """Runs in a worker thread: resolve URL, fetch + extract. No DB access here."""
    link = feed_link = entry.get("link")
    if not link:
        return None

    title = (entry.get("title") or "").strip() or "(untitled)"
    summary = _strip_html(entry.get("summary", ""))
    source_name = feed["name"]

    with httpx.Client(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        if "news.google.com" in link:
            # Google News titles end with " - Publisher"; the entry carries the real publisher.
            publisher = (entry.get("source") or {}).get("title")
            if publisher:
                source_name = publisher
                title = title.removesuffix(f" - {publisher}")
            try:
                link = decode_google_news_url(client, link) or link
            except Exception as exc:
                logger.info("google news decode failed for %s: %s", link, exc)

        final_url, clean_text = (link, None)
        if "news.google.com" not in link:
            final_url, clean_text = extract_article_text(client, link)

    extraction = "full"
    if not clean_text:
        # Publisher blocked us (403/paywall) or extraction failed. Keep the item with
        # what the feed gave us: a risk story known only by its headline should still
        # be classified and can still alert. Flagged so the briefing/UI can say so.
        clean_text = title if summary.lower().startswith(title.lower()[:40]) or not summary else f"{title}\n\n{summary}"
        extraction = "headline_only"

    return {
        "source": source_name,
        # url = the feed's link (stable dedup key across runs, even for Google News stubs);
        # canonical_url = the resolved publisher URL (what we show and cite).
        "url": canonicalize_url(feed_link),
        "canonical_url": canonicalize_url(final_url),
        "title": title,
        "author": entry.get("author"),
        # trust the text over the feed's label (an English Google News query returns
        # Arabic- and Japanese-edition outlets too); headlines are too short to detect
        "language": (detect_language(clean_text) if extraction == "full" else None) or feed.get("lang"),
        "published_at": _entry_published(entry),
        "clean_text": clean_text,
        "extraction": extraction,
    }


def run_ingest(db: Session, source_urls: list[str] | None = None) -> dict:
    """
    Fetch configured (or overridden) feeds, extract + store new articles.
    Dedup here is URL-level only; near-duplicate *story* clustering across
    different URLs happens in services/dedupe.py after embeddings exist.
    """
    feeds = SOURCES if not source_urls else [{"name": u, "url": u, "lang": None} for u in source_urls]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.max_article_age_hours)

    fetched = new_articles = duplicates = errors = filtered = 0
    per_feed: list[dict] = []
    todo: list[tuple[dict, object]] = []
    seen: set[str] = set()

    with httpx.Client(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        for feed in feeds:
            try:
                entries = fetch_feed_entries(client, feed["url"])
            except Exception as exc:
                logger.warning("could not fetch feed %s: %s", feed["url"], exc)
                per_feed.append({"feed": feed["url"], "ok": False, "error": str(exc)[:200]})
                errors += 1
                continue

            kept = 0
            for entry in entries:
                if kept >= settings.max_items_per_feed:
                    break
                fetched += 1
                published = _entry_published(entry)
                if published and published < cutoff:
                    filtered += 1
                    continue
                if feed.get("keyword_filter") and not _KEYWORD_RE.search(
                    f"{entry.get('title', '')} {_strip_html(entry.get('summary', ''))}"
                ):
                    filtered += 1
                    continue
                link = canonicalize_url(entry.get("link") or "")
                if not link or link in seen:
                    duplicates += 1
                    continue
                seen.add(link)
                todo.append((feed, entry))
                kept += 1
            per_feed.append({"feed": feed["url"], "ok": True, "entries": len(entries), "queued": kept})

    # Drop anything already stored (by feed link) before doing expensive fetches.
    if seen:
        existing = set(db.execute(select(Article.url).where(Article.url.in_(seen))).scalars())
        duplicates += sum(1 for _, e in todo if canonicalize_url(e.get("link")) in existing)
        todo = [(f, e) for f, e in todo if canonicalize_url(e.get("link")) not in existing]

    with ThreadPoolExecutor(max_workers=settings.fetch_concurrency) as pool:
        results = list(pool.map(lambda fe: _safe_process(*fe), todo))

    stored_canonicals = set()
    for item in results:
        if item is None:
            errors += 1
            continue
        # Same story reached via Google News *and* a direct feed resolves to the same publisher URL.
        if item["canonical_url"] in stored_canonicals or db.execute(
            select(Article.id).where(Article.canonical_url == item["canonical_url"])
        ).first():
            duplicates += 1
            continue
        stored_canonicals.add(item["canonical_url"])
        db.add(Article(fetched_at=datetime.now(timezone.utc), is_canonical=True, **item))
        new_articles += 1
    db.commit()

    logger.info("ingest: %s", per_feed)
    return {
        "fetched": fetched,
        "new_articles": new_articles,
        "duplicates": duplicates,
        "errors": errors,
        "filtered_out": filtered,
        "feeds": per_feed,
    }


def _safe_process(feed: dict, entry) -> dict | None:
    try:
        return _process_entry(feed, entry)
    except Exception:
        logger.exception("failed to process entry %s", entry.get("link"))
        return None
