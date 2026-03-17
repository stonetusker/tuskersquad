"""
Demo E-Commerce Application — TuskerSquad Test Target (ShopFlow)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from apps.backend.seed_data import seed
from apps.backend.routes.auth import router as auth_router
from apps.backend.routes.products import router as products_router
from apps.backend.routes.checkout import router as checkout_router
from apps.backend.routes.orders import router as orders_router
from apps.backend.routes.user import router as user_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed()
    yield


app = FastAPI(
    title="ShopFlow — Demo Store",
    description="TuskerSquad test target e-commerce application",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080", "http://127.0.0.1:5173", "http://127.0.0.1:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(checkout_router)
app.include_router(orders_router)
app.include_router(user_router)

# Serve demo UI at root
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def root_ui():
        index = os.path.join(static_dir, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
        return {"service": "ShopFlow", "note": "TuskerSquad test target"}
else:
    @app.get("/")
    def root():
        return {"service": "ShopFlow", "note": "TuskerSquad test target"}


@app.get("/health")
def health():
    bugs_active = [
        k for k, v in {
            "PRICE": os.getenv("BUG_PRICE", "false"),
            "SECURITY": os.getenv("BUG_SECURITY", "false"),
            "SLOW": os.getenv("BUG_SLOW", "false"),
        }.items() if v.lower() == "true"
    ]
    return {
        "status": "ok",
        "service": "shopflow-demo",
        "bugs_active": bugs_active,
    }
