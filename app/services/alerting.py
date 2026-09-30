from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, Article


def get_pending_alerts(db: Session) -> list[dict]:
    rows = db.execute(
        select(Alert, Article)
        .join(Article, Alert.article_id == Article.id)
        .where(Alert.acknowledged_at.is_(None))
        .order_by(Alert.raised_at.desc())
    ).all()

    return [
        {
            "alert_id": alert.id,
            "article_id": article.id,
            "title": article.title,
            "source": article.source,
            "url": article.canonical_url,
            "risk_score": float(alert.risk_score),
            "reason": alert.reason,
            "raised_at": alert.raised_at,
        }
        for alert, article in rows
    ]


def acknowledge_alert(db: Session, alert_id: int, acknowledged_by: str) -> bool:
    alert = db.get(Alert, alert_id)
    if not alert:
        return False
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = acknowledged_by
    db.commit()
    return True
