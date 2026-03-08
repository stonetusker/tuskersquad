"""
Database bootstrap
==================
Creates the SQLAlchemy engine and provides:
  - SessionLocal  : session factory
  - get_db()      : FastAPI dependency
  - init_db()     : called at startup, creates all tables with retry
"""

import logging
import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .models import Base

logger = logging.getLogger("langgraph.db")

POSTGRES_USER     = os.getenv("POSTGRES_USER",     "tusker")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "tusker")
POSTGRES_DB       = os.getenv("POSTGRES_DB",       "tuskersquad")
POSTGRES_HOST     = os.getenv("POSTGRES_HOST",     "tuskersquad-postgres")
POSTGRES_PORT     = os.getenv("POSTGRES_PORT",     "5432")

DATABASE_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
    connect_args={"connect_timeout": 10},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency: yields a DB session, always closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(max_retries: int = 30, delay: float = 2.0) -> None:
    """
    Create all ORM tables, retrying until Postgres is available.

    Retries for up to max_retries * delay seconds (default 60s).
    Raises on exhaustion so the container fails fast with a clear log.
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            # Connection succeeded — create tables
            Base.metadata.create_all(bind=engine)
            logger.info(
                "db_init_success tables_created attempt=%d/%d",
                attempt, max_retries,
            )
            return
        except (OperationalError, SQLAlchemyError) as exc:
            last_exc = exc
            logger.warning(
                "db_init attempt=%d/%d failed: %s — retrying in %.0fs",
                attempt, max_retries, exc.__class__.__name__, delay,
            )
            time.sleep(delay)

    # Exhausted all retries
    logger.error(
        "db_init_exhausted max_retries=%d last_error=%s",
        max_retries, last_exc,
    )
    raise RuntimeError(
        f"Database unavailable after {max_retries} attempts: {last_exc}"
    ) from last_exc
