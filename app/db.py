from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# psycopg (v3) is the installed driver; a bare postgresql:// URL would make
# SQLAlchemy look for psycopg2 and crash at import.
_url = settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def step_lock(name: str) -> Iterator[bool]:
    """
    Non-blocking Postgres advisory lock so overlapping scheduler runs (n8n fires
    every 5 min; a slow classify can take longer) skip instead of double-processing.
    Held on a dedicated connection because advisory locks are per-connection.
    """
    with engine.connect() as conn:
        got = conn.execute(text("SELECT pg_try_advisory_lock(hashtext(:n))"), {"n": name}).scalar()
        try:
            yield bool(got)
        finally:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(hashtext(:n))"), {"n": name})
