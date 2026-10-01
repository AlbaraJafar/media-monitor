import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """
    Shared-secret check for every non-health endpoint. Minimal on purpose: it stops
    anyone on the network from calling /approve or /deliver and forging the audit
    trail. Production would swap this for SSO identities so `approved_by` comes from
    the authenticated user rather than a request field.
    """
    if not settings.api_key:
        return
    if not key or not secrets.compare_digest(key, settings.api_key):
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")


# ---- Signed, expiring, read-only links to one briefing --------------------------
# A browser can't send X-API-Key, so the Slack "read the full briefing" link carries
# an HMAC over (briefing id, expiry) instead. It opens only that briefing, only for
# reading, and stops working after briefing_link_ttl_hours; the API key itself never
# appears in a URL.

def _briefing_sig(briefing_id: int, expires: int) -> str:
    msg = f"briefing-view:{briefing_id}:{expires}".encode()
    return hmac.new(settings.api_key.encode(), msg, hashlib.sha256).hexdigest()


def sign_briefing_link(briefing_id: int, ttl_hours: int | None = None) -> str:
    expires = int(time.time()) + (ttl_hours or settings.briefing_link_ttl_hours) * 3600
    base = settings.public_base_url.rstrip("/")
    # Path segments, not a query string: n8n HTML-escapes the Slack message, and an
    # "&" in the URL would come out as "&amp;" and break the link.
    return f"{base}/brief/{briefing_id}/view/{expires}/{_briefing_sig(briefing_id, expires)}"


def verify_briefing_link(briefing_id: int, expires: int, sig: str) -> bool:
    if not settings.api_key:
        return True  # auth disabled (local tinkering), same as require_api_key
    if expires < time.time():
        return False
    return secrets.compare_digest(sig, _briefing_sig(briefing_id, expires))
