from fastapi import FastAPI

from .db.database import init_db
from .api.workflow_routes import router as workflow_router

app = FastAPI(title="TuskerSquad LangGraph API")


@app.on_event("startup")
def startup_event():
    """
    Initialize database tables when the service starts.
    """
    init_db()


app.include_router(workflow_router, prefix="/api")
