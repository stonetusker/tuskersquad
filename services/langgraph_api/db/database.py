import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from services.langgraph_api.db.models import Base

logger = logging.getLogger(__name__)


def build_database_url():
    """
    Build database URL from environment variables.

    This avoids hardcoding credentials and aligns
    with container-based configuration.
    """

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    db = os.getenv("POSTGRES_DB", "tuskersquad")
    host = os.getenv("POSTGRES_HOST", "tuskersquad-postgres")
    port = os.getenv("POSTGRES_PORT", "5432")

    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = build_database_url()


engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def init_db():
    """
    Initialize database schema.
    """
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database schema initialized")
    except SQLAlchemyError as e:
        logger.error(f"Database initialization failed: {e}")
        raise


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
