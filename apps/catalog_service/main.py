"""
ShopFlow — Catalog Service  (port 8081)
========================================
Owns: products, inventory levels, price rules.

Intentional bugs (toggled via env vars):
  BUG_INVENTORY  — stock check returns wrong count (oversell bug)
  BUG_PRICE_RULE — discount calculation uses wrong base price

Exposes:
  GET  /products              — product catalogue
  GET  /products/{id}         — single product with stock level
  POST /products/{id}/reserve — reserve stock for an order
  GET  /health
  GET  /logs/events           — last N structured error events (for log_inspector agent)
"""

import os
import time
import logging
import uuid
from collections import deque
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel

# ── Bug toggles ───────────────────────────────────────────────────────────────
BUG_INVENTORY  = os.getenv("BUG_INVENTORY",  "false").lower() == "true"
BUG_PRICE_RULE = os.getenv("BUG_PRICE_RULE", "false").lower() == "true"

# ── Structured event log (in-memory ring buffer — agents read this) ───────────
_EVENT_LOG: deque = deque(maxlen=200)

def _log_event(level: str, service: str, event: str, detail: str, correlation_id: str = None):
    entry = {
        "id":             str(uuid.uuid4()),
        "timestamp":      datetime.utcnow().isoformat(),
        "level":          level,          # INFO | WARN | ERROR
        "service":        service,
        "event":          event,
        "detail":         detail,
        "correlation_id": correlation_id,
    }
    _EVENT_LOG.append(entry)
    logging.getLogger("catalog").log(
        logging.ERROR if level == "ERROR" else logging.WARNING if level == "WARN" else logging.INFO,
        "[%s] %s — %s", service, event, detail,
        extra={"correlation_id": correlation_id},
    )
    return entry


# ── In-memory product store ───────────────────────────────────────────────────
_PRODUCTS = {
    1: {"id": 1, "name": "Wireless Headphones", "price": 79.99,  "stock": 50},
    2: {"id": 2, "name": "USB-C Hub",           "price": 34.99,  "stock": 120},
    3: {"id": 3, "name": "Mechanical Keyboard", "price": 129.99, "stock": 30},
    4: {"id": 4, "name": "Monitor Stand",       "price": 49.99,  "stock": 0},   # out of stock
    5: {"id": 5, "name": "Webcam HD",           "price": 89.99,  "stock": 15},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_event("INFO", "catalog-service", "startup", "Catalog service started", "system")
    yield


app = FastAPI(title="ShopFlow Catalog Service", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ReserveRequest(BaseModel):
    quantity: int
    order_id: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    bugs = {k: True for k, v in {
        "BUG_INVENTORY": BUG_INVENTORY, "BUG_PRICE_RULE": BUG_PRICE_RULE
    }.items() if v}
    return {"status": "ok", "service": "catalog-service", "bugs_active": list(bugs.keys())}


@app.get("/products")
def list_products():
    return list(_PRODUCTS.values())


@app.get("/products/{product_id}")
def get_product(product_id: int):
    p = _PRODUCTS.get(product_id)
    if not p:
        _log_event("WARN", "catalog-service", "product_not_found",
                   f"product_id={product_id}", f"req-{product_id}")
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    stock = p["stock"]
    price = p["price"]

    # BUG: inventory reports wrong (too-high) stock → oversell
    if BUG_INVENTORY:
        reported_stock = stock + 999
        _log_event("WARN", "catalog-service", "inventory_count_inflated",
                   f"product_id={product_id} real_stock={stock} reported={reported_stock}",
                   f"req-{product_id}")
        stock = reported_stock

    # BUG: price rule multiplies by 1.35 (wrong VAT application)
    if BUG_PRICE_RULE:
        price = round(price * 1.35, 2)
        _log_event("WARN", "catalog-service", "price_rule_applied_incorrectly",
                   f"product_id={product_id} base={p['price']} computed={price}",
                   f"req-{product_id}")

    return {**p, "stock": stock, "price": price}


@app.post("/products/{product_id}/reserve")
def reserve_stock(product_id: int, req: ReserveRequest):
    p = _PRODUCTS.get(product_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    if BUG_INVENTORY:
        # Bug: always succeeds even when out of stock
        _log_event("ERROR", "catalog-service", "reservation_bypassed_stock_check",
                   f"product_id={product_id} qty={req.quantity} actual_stock={p['stock']}",
                   req.order_id)
        return {"reserved": True, "product_id": product_id,
                "quantity": req.quantity, "warning": "stock_check_bypassed"}

    if p["stock"] < req.quantity:
        _log_event("WARN", "catalog-service", "insufficient_stock",
                   f"product_id={product_id} requested={req.quantity} available={p['stock']}",
                   req.order_id)
        raise HTTPException(status_code=409,
                            detail=f"Insufficient stock: {p['stock']} available")

    p["stock"] -= req.quantity
    _log_event("INFO", "catalog-service", "stock_reserved",
               f"product_id={product_id} qty={req.quantity} remaining={p['stock']}",
               req.order_id)
    return {"reserved": True, "product_id": product_id,
            "quantity": req.quantity, "remaining_stock": p["stock"]}


@app.get("/logs/events")
def get_events(limit: int = 50, level: Optional[str] = None):
    """
    Structured event log endpoint — consumed by the log_inspector agent.
    Returns most-recent events first.
    """
    events = list(reversed(list(_EVENT_LOG)))
    if level:
        events = [e for e in events if e["level"] == level.upper()]
    return {"service": "catalog-service", "events": events[:limit], "total": len(events)}
