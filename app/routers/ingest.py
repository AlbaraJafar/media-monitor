from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db, step_lock
from app.schemas import IngestRequest, IngestResponse
from app.services.dedupe import run_dedupe
from app.services.ingestion import run_ingest

router = APIRouter()


@router.post("", response_model=IngestResponse)
def ingest(request: IngestRequest, db: Session = Depends(get_db)):
    with step_lock("ingest") as acquired:
        if not acquired:
            return IngestResponse(fetched=0, new_articles=0, duplicates=0, errors=0,
                                  feeds=[{"skipped": "previous ingest still running"}])
        result = run_ingest(db, source_urls=request.source_urls)
        # embed + cluster whatever's new, so classify only sees canonical stories
        result["dedupe"] = run_dedupe(db)
        return result
