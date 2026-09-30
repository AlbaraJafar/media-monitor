from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.alerting import acknowledge_alert, get_pending_alerts

router = APIRouter()


@router.get("/pending")
def pending(db: Session = Depends(get_db)):
    return get_pending_alerts(db)


class AckRequest(BaseModel):
    acknowledged_by: str


@router.post("/{alert_id}/ack")
def ack(alert_id: int, request: AckRequest, db: Session = Depends(get_db)):
    ok = acknowledge_alert(db, alert_id, request.acknowledged_by)
    return {"ok": ok}
