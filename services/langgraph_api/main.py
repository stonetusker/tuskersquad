"""
TuskerSquad LangGraph API
=========================
Entry point for the LangGraph orchestration service.
"""

import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db.database import init_db
from .api.workflow_routes import router as workflow_router

logger = logging.getLogger("langgraph.main")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="TuskerSquad LangGraph API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    """
    Initialize DB tables in a background thread so uvicorn starts
    immediately and health checks pass while the DB is still being
    set up (depends_on postgres:healthy means it IS up, but we still
    retry for the brief window before create_all completes).
    """
    def _init():
        try:
            init_db(max_retries=30, delay=2.0)
        except Exception:
            logger.exception("db_init_failed — DB operations will error until resolved")

    t = threading.Thread(target=_init, name="db-init", daemon=True)
    t.start()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "langgraph-api"}


# Mount ALL workflow routes under /api prefix
app.include_router(workflow_router, prefix="/api")
