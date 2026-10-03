"""
Two views of one briefing, both derived from the stored content_md:

- slack_summary(): the short, plain-text approval request. Slack rejects a section
  block over 3,000 characters ("invalid_blocks"), and the n8n Slack node (v2.2)
  sends the message as plain_text, so this is plain text and hard-capped well
  under the limit — trimmed at a line boundary with a pointer to the full text,
  never cut mid-sentence.
- render_html(): the full briefing for the analyst's browser, opened from the
  signed link. The content is model output derived from scraped articles, so
  every piece of it is HTML-escaped; only citation URLs we stored become links.
"""
import html
import re

from app.config import settings
from app.models import Briefing
from app.security import sign_briefing_link

SLACK_BLOCK_LIMIT = 3000
SLACK_BUDGET = 2800  # headroom under the hard limit for n8n's escaping of & < >

_CITE = re.compile(r"\[A(\d+)\]")


def _section(md: str, heading: str) -> str:
    """Body of a '## heading' section, up to the next '## ' heading."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", md, flags=re.M | re.S)
    return m.group(1).strip() if m else ""


def _plain(md: str) -> str:
    """Markdown -> readable plain text for a Slack plain_text block."""
    text = re.sub(r"\s*\[A\d+\]", "", md)  # citations live in the full view
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _trim(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    cut = text[:budget].rsplit("\n", 1)[0] or text[:budget].rsplit(" ", 1)[0]
    return cut.rstrip() + "\n… (continued in the full briefing)"


def is_degraded(b: Briefing) -> bool:
    """
    From the content, not the status: approval moves a degraded briefing to
    approved/delivered, and the DG office copy must still say it is degraded
    rather than "all claims verified".
    """
    return b.status == "degraded" or "DEGRADED BRIEFING" in (b.draft_md or b.content_md or "")[:300]


def verification_status(b: Briefing) -> str:
    if is_degraded(b):
        return "n/a"
    claims = b.unverified_claims or []
    if any(c.get("claim") == "(verifier did not run)" for c in claims):
        return "not_run"
    return "flagged" if claims else "passed"


def themes_covered(b: Briefing) -> int:
    return len(re.findall(r"^###\s+\S", _section(b.content_md, "Coverage by Theme"), flags=re.M))


def sources_cited(b: Briefing) -> int:
    return len(set(_CITE.findall(b.content_md)))


def slack_summary(b: Briefing, view_url: str, purpose: str = "approval") -> str:
    """purpose="approval": the request to the analyst. purpose="delivery": the approved copy for the DG office."""
    verification = verification_status(b)
    n_flagged = len(b.unverified_claims or [])
    if purpose == "delivery":
        verdict = {
            "passed": "All claims were verified against their sources.",
            "flagged": f"Approved with {n_flagged} claim(s) the verifier could not confirm — see the full briefing.",
            "not_run": "Approved without automatic claim verification (the verifier did not run).",
            "n/a": "Approved DEGRADED briefing (no AI summary).",
        }[verification]
        when = f" at {b.approved_at:%H:%M} UTC" if b.approved_at else ""
        header = f"Daily Media Briefing — {b.briefing_date:%Y-%m-%d}\nApproved by {b.approved_by or 'unknown'}{when}"
        footer = f"Full briefing with sources:\n{view_url}"
    else:
        verdict = {
            "passed": "All claims verified against their sources.",
            "flagged": f"{n_flagged} claim(s) could NOT be verified against their source — check them in the full briefing.",
            "not_run": "Claim verification did not run — check every cited claim before approving.",
            "n/a": "DEGRADED briefing (no AI summary) — manual review required.",
        }[verification]
        header = f"Daily Media Briefing — {b.briefing_date:%Y-%m-%d}   [{b.status.upper()}]"
        footer = f"Read the full briefing before approving:\n{view_url}"
    counts = (f"{themes_covered(b)} themes covered · {sources_cited(b)} sources cited · "
              f"{n_flagged} unverified claims flagged")

    if is_degraded(b):
        body = _plain(b.content_md.split("\n## ")[0])
    else:
        body = _plain(_section(b.content_md, "Headline Summary")) or "(no headline summary section in this draft)"
        respond = _section(b.content_md, "Items Requiring a Response")
        if respond and "none today" not in respond.lower():
            body += "\n\nItems requiring a response:\n" + _plain(respond)

    fixed = "\n\n".join([header, "", counts, verdict, footer])
    body = _trim(body, SLACK_BUDGET - len(fixed))
    text = "\n\n".join([header, body, counts, verdict, footer])
    assert len(text) <= SLACK_BLOCK_LIMIT, len(text)
    return text


def headline_text(b: Briefing) -> str:
    """The briefing's headline section as plain text (the degraded banner for a degraded one)."""
    if is_degraded(b):
        return _plain(b.content_md.split("\n## ")[0])
    return _plain(_section(b.content_md, "Headline Summary")) or "(no headline summary in this draft)"


def summary_fields(b: Briefing) -> dict:
    view_url = sign_briefing_link(b.id)
    return {
        "headline_text": headline_text(b),
        "briefing_date": b.briefing_date,
        "verification": verification_status(b),
        "themes_covered": themes_covered(b),
        "sources_cited": sources_cited(b),
        "view_url": view_url,
        "slack_summary": slack_summary(b, view_url),
    }


def delivery_fields(b: Briefing) -> dict:
    """What the DG office channel receives: the approved content, bounded like the approval message."""
    view_url = sign_briefing_link(b.id, ttl_hours=settings.delivery_link_ttl_hours)
    return {"view_url": view_url, "delivery_summary": slack_summary(b, view_url, purpose="delivery")}


# ------------------------------------------------------------------ HTML view --

def _inline(escaped: str, links: dict[int, str]) -> str:
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)

    def cite(m: re.Match) -> str:
        aid = int(m.group(1))
        url = links.get(aid)
        return f'<a href="{html.escape(url)}" rel="noopener noreferrer">[A{aid}]</a>' if url else f"[A{aid}]"

    return _CITE.sub(cite, out)


def render_html(b: Briefing) -> str:
    links = {c["article_id"]: c["url"] for c in (b.citations_json or [])
             if str(c.get("url", "")).startswith(("http://", "https://"))}
    sources = {}
    for c in b.citations_json or []:
        sources.setdefault(c["article_id"], (c.get("source", ""), c.get("url", "")))

    body, in_list = [], False
    for raw in b.content_md.splitlines():
        line = html.escape(raw.rstrip())
        bullet = re.match(r"^\s*[-*]\s+(.*)", line)
        if in_list and not bullet:
            body.append("</ul>")
            in_list = False
        if not line.strip():
            continue
        if line.startswith("### "):
            body.append(f"<h3>{_inline(line[4:], links)}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:], links)}</h2>")
        elif line.startswith("&gt; "):
            body.append(f'<p class="banner">{_inline(line[5:], links)}</p>')
        elif line.strip() == "---":
            body.append("<hr>")
        elif bullet:
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(bullet.group(1), links)}</li>")
        else:
            body.append(f"<p>{_inline(line, links)}</p>")
    if in_list:
        body.append("</ul>")

    src_rows = "".join(
        f'<li>[A{aid}] {html.escape(src)} — '
        + (f'<a href="{html.escape(url)}" rel="noopener noreferrer">{html.escape(url[:90])}</a>'
           if url.startswith(("http://", "https://")) else html.escape(url))
        + "</li>"
        for aid, (src, url) in sorted(sources.items())
    )
    approved = (f"Approved by {html.escape(b.approved_by)} at {b.approved_at:%Y-%m-%d %H:%M} UTC"
                if b.approved_by else "Not yet approved")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Briefing {b.briefing_date:%Y-%m-%d}</title>
<style>
body{{font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem;color:#1d2433}}
.meta{{color:#5b6475;font-size:13px;border-bottom:1px solid #e3e6ec;padding-bottom:.75rem}}
.banner{{background:#fff4e5;border-left:4px solid #e8a33d;padding:.5rem .75rem}}
h2{{margin-top:1.75rem;border-bottom:1px solid #e3e6ec;padding-bottom:.25rem}} a{{color:#2156c8}}
li{{margin:.25rem 0}} .sources{{font-size:13px;color:#5b6475}}
</style></head><body>
<p class="meta">Briefing #{b.id} · {b.briefing_date:%Y-%m-%d} · status <strong>{html.escape(b.status)}</strong> ·
verification <strong>{verification_status(b)}</strong> · {approved}</p>
{''.join(body)}
<h2>Sources cited</h2><ul class="sources">{src_rows or '<li>none</li>'}</ul>
</body></html>"""
