from fastapi import FastAPI

from services.langgraph_api.health import router


app = FastAPI(

    title="TuskerSquad LangGraph API"
)

app.include_router(router)
