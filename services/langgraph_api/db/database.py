from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.langgraph_api.db.models import Base

DATABASE_URL = "postgresql://tusker:tusker@tuskersquad-postgres:5432/tuskersquad"

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

def init_db():
    """
    Initialize database schema for TuskerSquad.

    This will create tables automatically for all SQLAlchemy models
    defined in models.py if they do not already exist.
    """
    Base.metadata.create_all(bind=engine, checkfirst=True)
