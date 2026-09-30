from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db, step_lock
from app.schemas import ClassifyRequest, ClassifyResponse
from app.services.classification import run_classify

router = APIRouter()


@router.post("", response_model=ClassifyResponse)
def classify(request: ClassifyRequest, db: Session = Depends(get_db)):
    with step_lock("classify") as acquired:
        if not acquired:
            # n8n fires every 5 min; if the last batch is still running, skip rather than double-classify
            return ClassifyResponse(classified=0, high_risk_flagged=0, errors=0)
        result = run_classify(db, article_ids=request.article_ids)

    # Every item failing means *both* the primary and the fallback model are down
    # (or misconfigured) — systemic, not a few bad articles. Return 5xx so n8n's
    # Error Workflow pages on-call; a 200 here would mean risk alerts silently stop.
    # A primary-only outage is absorbed by the fallback and reported in fallback_used.
    if result["errors"] and not result["classified"]:
        raise HTTPException(503, detail={"message": "classification failed for every article on both the "
                                         "primary and fallback model — check provider status, API keys and billing", **result})
    return result
