"""
ShopFlow — Order Service  (port 8082)
======================================
Owns: orders, checkout flow, payment records.

Calls catalog-service to reserve stock, user-service to validate session.
This is the critical cross-service path — bugs here produce correlated
errors visible in multiple service logs.

Intentional bugs:
  BUG_SLOW        — checkout sleeps 3s (latency regression)
  BUG_PRICE       — total is multiplied 1.35 (double-VAT when catalog also bugs)
  BUG_NO_ROLLBACK — stock reservation is not rolled back on payment failure

Exposes:
  POST /checkout
  GET  /orders
  GET  /orders/{id}
  GET  /health
  GET  /logs/events
"""

import os
import time
import uuid
import logging
import httpx
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Bug toggles ───────────────────────────────────────────────────────────────
BUG_SLOW        = os.getenv("BUG_SLOW",        "false").lower() == "true"
BUG_PRICE       = os.getenv("BUG_PRICE",       "false").lower() == "true"
BUG_NO_ROLLBACK = os.getenv("BUG_NO_ROLLBACK", "false").lower() == "true"

# ── Service URLs ──────────────────────────────────────────────────────────────
CATALOG_URL = os.getenv("CATALOG_SERVICE_URL", "http://tuskersquad-catalog:8081")
USER_URL    = os.getenv("USER_SERVICE_URL",    "http://tuskersquad-user:8083")

# ── Structured event log ──────────────────────────────────────────────────────
_EVENT_LOG: deque = deque(maxlen=200)

def _log_event(level: str, service: str, event: str, detail: str, correlation_id: str = None):
    entry = {
        "id":             str(uuid.uuid4()),
        "timestamp":      datetime.utcnow().isoformat(),
        "level":          level,
        "service":        service,
        "event":          event,
        "detail":         detail,
        "correlation_id": correlation_id,
    }
    _EVENT_LOG.append(entry)
    logging.getLogger("order").log(
        logging.ERROR if level == "ERROR" else logging.WARNING if level == "WARN" else logging.INFO,
        "[%s] %s — %s  corr=%s", service, event, detail, correlation_id,
    )
    return entry


# ── In-memory order store ─────────────────────────────────────────────────────
_ORDERS: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_event("INFO", "order-service", "startup", "Order service started", "system")
    yield


app = FastAPI(title="ShopFlow Order Service", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class OrderItem(BaseModel):
    product_id: int
    quantity:   int


class CheckoutRequest(BaseModel):
    items: List[OrderItem]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_product(product_id: int, correlation_id: str) -> Optional[dict]:
    """Call catalog-service to get product details."""
    try:
        r = httpx.get(f"{CATALOG_URL}/products/{product_id}", timeout=5)
        if r.status_code == 200:
            return r.json()
        _log_event("WARN", "order-service", "catalog_lookup_failed",
                   f"product_id={product_id} status={r.status_code}", correlation_id)
        return None
    except Exception as exc:
        _log_event("ERROR", "order-service", "catalog_service_unreachable",
                   f"product_id={product_id} error={exc}", correlation_id)
        return None


def _reserve_stock(product_id: int, quantity: int, order_id: str, correlation_id: str) -> bool:
    """Call catalog-service to reserve stock."""
    try:
        r = httpx.post(
            f"{CATALOG_URL}/products/{product_id}/reserve",
            json={"quantity": quantity, "order_id": order_id},
            timeout=5,
        )
        if r.status_code == 200:
            return True
        _log_event("WARN", "order-service", "stock_reservation_failed",
                   f"product_id={product_id} qty={quantity} status={r.status_code}",
                   correlation_id)
        return False
    except Exception as exc:
        _log_event("ERROR", "order-service", "catalog_reserve_unreachable",
                   f"error={exc}", correlation_id)
        return False


def _validate_user(authorization: str, correlation_id: str) -> Optional[dict]:
    """Call user-service to validate the bearer token."""
    try:
        r = httpx.get(
            f"{USER_URL}/auth/validate",
            headers={"Authorization": authorization},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json()
        _log_event("WARN", "order-service", "user_auth_failed",
                   f"status={r.status_code}", correlation_id)
        return None
    except Exception as exc:
        _log_event("ERROR", "order-service", "user_service_unreachable",
                   f"error={exc}", correlation_id)
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    bugs = {k: True for k, v in {
        "BUG_SLOW": BUG_SLOW,
        "BUG_PRICE": BUG_PRICE,
        "BUG_NO_ROLLBACK": BUG_NO_ROLLBACK,
    }.items() if v}
    return {"status": "ok", "service": "order-service", "bugs_active": list(bugs.keys())}


@app.post("/checkout")
def checkout(
    request: CheckoutRequest,
    authorization: str = Header(default=None),
    x_correlation_id: str = Header(default=None),
):
    correlation_id = x_correlation_id or str(uuid.uuid4())
    order_id = str(uuid.uuid4())

    # ── Auth: validate with user-service ──────────────────────────────────────
    user = None
    if authorization:
        user = _validate_user(authorization, correlation_id)
    if user is None:
        # Fallback: no-auth mode for demo (log the skip)
        _log_event("WARN", "order-service", "checkout_unauthenticated",
                   "proceeding without validated user token", correlation_id)
        user = {"user_id": 1, "email": "guest@demo.local"}

    # ── Performance bug ───────────────────────────────────────────────────────
    if BUG_SLOW:
        _log_event("WARN", "order-service", "checkout_slow_path_active",
                   "sleeping 3s due to BUG_SLOW flag", correlation_id)
        time.sleep(3)

    # ── Resolve products from catalog-service ──────────────────────────────────
    total = 0.0
    resolved_items = []
    reservation_failures = []

    for item in request.items:
        product = _get_product(item.product_id, correlation_id)
        if product is None:
            _log_event("ERROR", "order-service", "product_resolution_failed",
                       f"product_id={item.product_id}", correlation_id)
            raise HTTPException(status_code=422,
                                detail=f"Product {item.product_id} could not be resolved from catalog")

        line_total = product["price"] * item.quantity
        total += line_total
        resolved_items.append({
            "product_id":   item.product_id,
            "product_name": product["name"],
            "unit_price":   product["price"],
            "quantity":     item.quantity,
            "line_total":   line_total,
        })

        # Reserve stock in catalog
        ok = _reserve_stock(item.product_id, item.quantity, order_id, correlation_id)
        if not ok:
            reservation_failures.append(item.product_id)

    # ── Pricing bug ───────────────────────────────────────────────────────────
    if BUG_PRICE:
        inflated = round(total * 1.35, 2)
        _log_event("ERROR", "order-service", "price_inflated_by_bug",
                   f"correct_total={total:.2f} inflated_total={inflated:.2f} order_id={order_id}",
                   correlation_id)
        total = inflated

    total = round(total, 2)

    # ── Reservation failures without rollback (bug) ───────────────────────────
    if reservation_failures:
        if BUG_NO_ROLLBACK:
            _log_event("ERROR", "order-service", "order_created_with_failed_reservations",
                       f"order_id={order_id} failed_products={reservation_failures} "
                       "NO ROLLBACK — stock consistency violated",
                       correlation_id)
            # Continue anyway — this is the bug: no rollback
        else:
            _log_event("WARN", "order-service", "order_aborted_insufficient_stock",
                       f"order_id={order_id} failed_products={reservation_failures}",
                       correlation_id)
            raise HTTPException(status_code=409,
                                detail=f"Insufficient stock for products: {reservation_failures}")

    # ── Persist order ─────────────────────────────────────────────────────────
    order = {
        "order_id":       order_id,
        "user_id":        user.get("user_id", 1),
        "items":          resolved_items,
        "total":          total,
        "status":         "created",
        "correlation_id": correlation_id,
        "created_at":     datetime.utcnow().isoformat(),
    }
    _ORDERS[order_id] = order

    _log_event("INFO", "order-service", "order_created",
               f"order_id={order_id} total={total} items={len(resolved_items)}", correlation_id)

    return order


@app.get("/orders")
def list_orders(authorization: str = Header(default=None)):
    # No auth check intentionally — tests auth bypass
    return list(_ORDERS.values())


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    o = _ORDERS.get(order_id)
    if not o:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return o


@app.get("/logs/events")
def get_events(limit: int = 50, level: Optional[str] = None):
    events = list(reversed(list(_EVENT_LOG)))
    if level:
        events = [e for e in events if e["level"] == level.upper()]
    return {"service": "order-service", "events": events[:limit], "total": len(events)}
