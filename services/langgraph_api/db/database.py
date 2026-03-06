import os
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

from .models import Base

# Read database connection info from environment (docker-compose sets these)
POSTGRES_USER = os.getenv("POSTGRES_USER", "tusker")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "tusker")
POSTGRES_DB = os.getenv("POSTGRES_DB", "tuskersquad")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

DATABASE_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# Engine and session factory exported for repository usage
engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db():
    """FastAPI dependency that yields a DB session."""

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def init_db(retries: int = 10, delay: float = 2.0):
    """Attempt to create tables, retrying until Postgres is available.

    This avoids the fast-fail startup when Postgres container is still
    initializing. Defaults to 10 attempts with a 2s delay.
    """

    attempt = 0
    while attempt < retries:
        try:
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError:
            attempt += 1
            time.sleep(delay)

    # Final attempt (let exception bubble)
    Base.metadata.create_all(bind=engine)
