from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db.database import init_db
from .api.workflow_routes import router as workflow_router

app = FastAPI(title="TuskerSquad LangGraph API")

# Allow services and frontend to query LangGraph during development
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
    Initialize database tables when the service starts.
    """
    init_db()


app.include_router(workflow_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "langgraph-api"}
