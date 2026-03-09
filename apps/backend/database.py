from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Use an explicit absolute path inside the container.
# /tmp/shopflow.db is fine for a demo app — data does not need to persist across restarts.
DATABASE_URL = "sqlite:////tmp/shopflow.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()
