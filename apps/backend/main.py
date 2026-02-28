from fastapi import FastAPI

from apps.backend.seed_data import seed

from apps.backend.routes.auth import router as auth_router


seed()

app=FastAPI(

    title="TuskerSquad Ecommerce"
)


app.include_router(auth_router)


@app.get("/health")

def health():

    return {"status":"ok"}
