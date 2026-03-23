"""
Demo E-Commerce Application — TuskerSquad Test Target (ShopFlow)

Exposes a /logs/events endpoint in the same format as the microservices
(catalog-service, order-service, user-service). The Log Inspector agent
polls this endpoint on the ephemeral PR container to collect server-side
evidence for the Correlator's cross-layer root cause analysis.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from collections import deque
from datetime import datetime
from typing import Optional
import uuid
import os

# ── Structured event log ──────────────────────────────────────────────────────
# Ring buffer of structured events — same format as catalog/order/user services.
# Populated by checkout and auth handlers via log_event().
# Read by the TuskerSquad Log Inspector agent at GET /logs/events.
_EVENT_LOG: deque = deque(maxlen=200)


def log_event(level: str, event: str, detail: str, correlation_id: str = None) -> dict:
    """
    Append a structured event to the in-memory log buffer.
    level:          INFO | WARN | ERROR
    event:          machine-readable event name (matched by Log Inspector rules)
    detail:         human-readable description
    correlation_id: optional request-level ID linking events across services
    """
    entry = {
        "id":             str(uuid.uuid4()),
        "timestamp":      datetime.utcnow().isoformat(),
        "level":          level,
        "service":        "shopflow-backend",
        "event":          event,
        "detail":         detail,
        "correlation_id": correlation_id or str(uuid.uuid4()),
    }
    _EVENT_LOG.append(entry)
    return entry

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


@app.get("/logs/events")
def get_log_events(limit: int = 50, level: Optional[str] = None):
    """
    Structured event log — consumed by the TuskerSquad Log Inspector agent.

    Returns the most-recent events first. The Log Inspector polls this endpoint
    on the ephemeral PR container alongside the permanent microservices
    (catalog-service, order-service, user-service), combining all server-side
    evidence for the Correlator agent's cross-layer root cause analysis.

    Event names matched by the Correlator:
      price_inflated_by_bug        → fires price_bug root cause chain
      auth_bypass_active           → fires auth_jwt root cause chain
      checkout_slow_path_active    → fires latency root cause chain
    """
    events = list(reversed(list(_EVENT_LOG)))
    if level:
        events = [e for e in events if e["level"] == level.upper()]
    return {
        "service": "shopflow-backend",
        "events":  events[:limit],
        "total":   len(events),
    }
