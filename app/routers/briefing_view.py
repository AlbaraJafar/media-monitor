from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Briefing
from app.security import verify_briefing_link
from app.services.briefing_render import render_html

router = APIRouter()

# Deliberately NOT behind require_api_key: this is what the analyst opens from the
# Slack link in a browser. Access is the signed, expiring link instead.
_HEADERS = {
    # the page links out to source articles: never leak the signed URL as a Referer
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
    "X-Robots-Tag": "noindex",
    "Cache-Control": "private, no-store",
}


@router.get("/brief/{briefing_id}/view/{expires}/{sig}", response_class=HTMLResponse, include_in_schema=False)
def view_briefing(briefing_id: int, expires: int, sig: str, db: Session = Depends(get_db)):
    if not verify_briefing_link(briefing_id, expires, sig):
        raise HTTPException(403, "This briefing link is invalid or has expired. Ask for a fresh one.")
    briefing = db.get(Briefing, briefing_id)
    if not briefing:
        raise HTTPException(404, "briefing not found")
    return HTMLResponse(render_html(briefing), headers=_HEADERS)
