from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://tusker:tusker@postgres:5432/tuskersquad"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency to provide DB session.
    """
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database tables.
    Called during application startup.
    """
    from services.langgraph_api.db import models

    Base.metadata.create_all(bind=engine)
