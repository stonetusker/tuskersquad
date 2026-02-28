from fastapi import FastAPI

from apps.backend.seed_data import seed

from apps.backend.routes.auth import router as auth_router
from apps.backend.routes.products import router as products_router
from apps.backend.routes.checkout import router as checkout_router
from apps.backend.routes.orders import router as orders_router


seed()

app = FastAPI(

    title="TuskerSquad Ecommerce"
)


app.include_router(auth_router)

app.include_router(products_router)

app.include_router(checkout_router)

app.include_router(orders_router)


@app.get("/health")

def health():

    return {"status": "ok"}
