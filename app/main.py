import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text

from app.db import engine
from app.routers import alerts, ask, briefing, classify, ingest, ops
from app.security import require_api_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load (and on first boot, download ~2GB of) embedding weights in the background,
    # so the first /ingest doesn't stall for minutes inside an n8n HTTP call.
    def _warm():
        from app.services.embeddings import get_embedder
        get_embedder()
        logging.getLogger("startup").info("embedding model ready")

    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(
    title="Media Monitoring Agent",
    description="Forward Deployed AI Engineer case study — Consulum. "
                "Click Authorize and paste the API_KEY from .env to call endpoints.",
    version="0.2.0",
    lifespan=lifespan,
)

auth = [Depends(require_api_key)]
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"], dependencies=auth)
app.include_router(classify.router, prefix="/classify", tags=["classify"], dependencies=auth)
app.include_router(briefing.router, prefix="/brief", tags=["briefing"], dependencies=auth)
app.include_router(alerts.router, prefix="/alerts", tags=["alerts"], dependencies=auth)
app.include_router(ask.router, prefix="/ask", tags=["ask"], dependencies=auth)
app.include_router(ops.router, tags=["ops"], dependencies=auth)


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    from app.services.embeddings import _load
    return {"status": "ok", "db": "ok", "embedder_loaded": _load.cache_info().currsize > 0}
