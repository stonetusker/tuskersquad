from fastapi import FastAPI

from services.langgraph_api.api.workflow_routes import router as workflow_router

app = FastAPI()

app.include_router(workflow_router)
