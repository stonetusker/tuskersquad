from fastapi import APIRouter
import httpx
import os

router = APIRouter()

OLLAMA = os.getenv(
    "OLLAMA_HOST",
    "http://host.docker.internal:11434"
)


@router.get("/health/llm")

async def llm_health():

    async with httpx.AsyncClient(timeout=20) as client:

        r = await client.get(

            f"{OLLAMA}/api/tags"

        )

        r.raise_for_status()

        return {

            "status": "ok",

            "models": r.json()
        }