from fastapi import FastAPI, Request
import httpx

app = FastAPI()

LANGGRAPH_URL = "http://tuskersquad-langgraph:8000"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/gitea/webhook")
async def gitea_webhook(request: Request):
    payload = await request.json()

    print("Webhook received from Gitea")
    print(payload)

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{LANGGRAPH_URL}/workflow/start",
            json={
                "repo": payload.get("repository", {}).get("name"),
                "branch": "feature",
                "pr_number": 1
            }
        )

    return {"status": "workflow triggered"}
