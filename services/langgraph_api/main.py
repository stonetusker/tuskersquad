from fastapi import FastAPI

from services.langgraph_api.db.database import init_db
from services.langgraph_api.api.workflow_routes import router as workflow_router

app = FastAPI()

@app.on_event("startup")
def startup():
    init_db()

app.include_router(workflow_router)
