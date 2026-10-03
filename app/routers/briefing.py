from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Briefing
from app.schemas import BriefingRequest, BriefingResponse
from app.services.briefing import run_briefing
from app.services.briefing_render import delivery_fields, summary_fields

router = APIRouter()


@router.post("", response_model=BriefingResponse)
def create_briefing(request: BriefingRequest, db: Session = Depends(get_db)):
    briefing = run_briefing(db, briefing_date=request.briefing_date, include_synthetic=request.include_synthetic,
                            synthetic_only=request.synthetic_only)
    return BriefingResponse(
        briefing_id=briefing.id,
        status=briefing.status,
        content_md=briefing.content_md,
        citations=briefing.citations_json,
        unverified_claim_count=len(briefing.unverified_claims),
        created_at=briefing.created_at,
        **summary_fields(briefing),
    )


@router.get("/{briefing_id}")
def get_briefing(briefing_id: int, db: Session = Depends(get_db)):
    briefing = db.get(Briefing, briefing_id)
    if not briefing:
        raise HTTPException(404, "briefing not found")
    return {
        "briefing_id": briefing.id, "briefing_date": briefing.briefing_date, "status": briefing.status,
        "content_md": briefing.content_md, "draft_md": briefing.draft_md,
        "unverified_claim_count": len(briefing.unverified_claims),
        "approved_by": briefing.approved_by, "approved_at": briefing.approved_at,
        "disapproved_by": briefing.disapproved_by, "disapproved_at": briefing.disapproved_at,
        "delivered_at": briefing.delivered_at, "created_at": briefing.created_at,
        **summary_fields(briefing),
    }


class ApproveRequest(BaseModel):
    approved_by: str = Field(..., min_length=2)
    edited_content_md: str | None = None  # analyst may correct the draft before approving


@router.post("/{briefing_id}/approve")
def approve_briefing(briefing_id: int, request: ApproveRequest, db: Session = Depends(get_db)):
    briefing = db.get(Briefing, briefing_id)
    if not briefing:
        raise HTTPException(404, "briefing not found")
    if briefing.status not in ("draft", "degraded"):
        raise HTTPException(409, f"briefing is already {briefing.status}")

    # draft_md keeps the untouched AI draft; the diff against content_md is the
    # analyst-correction signal that feeds the gold set and prompt improvements.
    if request.edited_content_md:
        briefing.content_md = request.edited_content_md
    briefing.status = "approved"
    briefing.approved_by = request.approved_by
    briefing.approved_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "approved", "briefing_id": briefing.id, "edited": bool(request.edited_content_md)}


class DisapproveRequest(BaseModel):
    disapproved_by: str = Field(..., min_length=2)


@router.post("/{briefing_id}/disapprove")
def disapprove_briefing(briefing_id: int, request: DisapproveRequest, db: Session = Depends(get_db)):
    """
    An explicit "Disapprove" from the named analyst. Records who and when and closes
    the briefing: status "disapproved" can never be delivered, because /deliver
    accepts only "approved". Fails closed at the API, not just in n8n.
    """
    briefing = db.get(Briefing, briefing_id)
    if not briefing:
        raise HTTPException(404, "briefing not found")
    if briefing.status not in ("draft", "degraded"):
        raise HTTPException(409, f"briefing is already {briefing.status}")
    briefing.status = "disapproved"
    briefing.disapproved_by = request.disapproved_by
    briefing.disapproved_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "disapproved", "briefing_id": briefing.id, "disapproved_by": briefing.disapproved_by}


@router.post("/{briefing_id}/deliver")
def mark_delivered(briefing_id: int, db: Session = Depends(get_db)):
    briefing = db.get(Briefing, briefing_id)
    if not briefing:
        raise HTTPException(404, "briefing not found")
    if briefing.status != "approved":
        raise HTTPException(400, f"briefing must be approved before delivery (status={briefing.status})")
    briefing.status = "delivered"
    briefing.delivered_at = datetime.now(timezone.utc)
    db.commit()
    # The status flip is the technical gate (only an approved briefing gets here);
    # delivery_summary is what n8n posts to the DG office channel next.
    return {"status": "delivered", "briefing_id": briefing.id, "content_md": briefing.content_md,
            "approved_by": briefing.approved_by, "delivered_at": briefing.delivered_at,
            **delivery_fields(briefing)}
