import secrets

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
