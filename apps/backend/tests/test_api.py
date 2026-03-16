"""
ShopFlow API tests — committed into the shopflow repository.

These tests are run by the TuskerSquad Backend Engineer agent against
the ephemeral PR container after deployment. They cover the full
happy path so a clean PR shows all tests passing.

Run locally from project root:
    pytest apps/backend/tests/ -v

Credentials match seed_data.py:
    email:    test@example.com
    password: password

Product prices match seed_data.py:
    product_id=1  Pro Laptop 16"     1299.00
    product_id=2  Mechanical Keyboard  149.99
    product_id=3  4K Monitor 27"      449.00
    product_id=4  Wireless Mouse        59.99
"""
import os
import pytest
from fastapi.testclient import TestClient
from apps.backend.main import app

client = TestClient(app)

DEMO_EMAIL    = "test@example.com"
DEMO_PASSWORD = "password"


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_token() -> str:
    r = client.post("/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Auth tests ─────────────────────────────────────────────────────────────────

def test_login_valid_credentials():
    """Valid credentials must return an access token."""
    r = client.post("/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_password():
    """Wrong password must return 401."""
    r = client.post("/login", json={"email": DEMO_EMAIL, "password": "wrongpassword"})
    assert r.status_code == 401


def test_login_unknown_email():
    """Unknown email must return 401."""
    r = client.post("/login", json={"email": "nobody@shopflow.io", "password": "password"})
    assert r.status_code == 401


# ── Product tests ──────────────────────────────────────────────────────────────

def test_products_list():
    """GET /products returns a non-empty list with id, name, price fields."""
    r = client.get("/products")
    assert r.status_code == 200
    products = r.json()
    assert isinstance(products, list)
    assert len(products) > 0
    for p in products:
        assert "id"    in p
        assert "name"  in p
        assert "price" in p
        assert p["price"] > 0


def test_product_by_id():
    """GET /products/1 returns the first seeded product."""
    r = client.get("/products/1")
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == 1
    assert "name"  in p
    assert "price" in p
    assert p["price"] == pytest.approx(1299.00, abs=0.01)


def test_product_not_found():
    """GET /products/99999 must return 404."""
    r = client.get("/products/99999")
    assert r.status_code == 404


def test_product_search():
    """GET /products/search returns results matching the query."""
    r = client.get("/products/search?q=Laptop")
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert body["count"] >= 1
    assert any("Laptop" in p["name"] for p in body["results"])


def test_product_search_no_results():
    """GET /products/search with no match returns empty results."""
    r = client.get("/products/search?q=xyznotaproduct99999")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["results"] == []


def test_product_recommendations():
    """GET /products/recommendations returns a list of products."""
    r = client.get("/products/recommendations")
    assert r.status_code == 200
    body = r.json()
    assert "recommendations" in body
    assert isinstance(body["recommendations"], list)


# ── Checkout tests ─────────────────────────────────────────────────────────────

def test_checkout_single_item():
    """
    Checkout with product_id=1, quantity=1.
    Expected total = 1299.00 (no bug flags active).
    """
    os.environ["BUG_PRICE"] = "false"
    token = get_token()
    r = client.post(
        "/checkout",
        headers=auth(token),
        json={"items": [{"product_id": 1, "quantity": 1}]}
    )
    assert r.status_code == 200
    body = r.json()
    assert "order_id" in body
    assert "total"    in body
    assert body["total"] == pytest.approx(1299.00, abs=0.01), (
        f"Expected 1299.00 but got {body['total']} — is BUG_PRICE active?"
    )


def test_checkout_multiple_items():
    """Checkout with multiple items — total equals sum of individual prices."""
    os.environ["BUG_PRICE"] = "false"
    token = get_token()

    # Get actual prices from the API so the test is data-driven
    products = client.get("/products").json()
    p1 = next(p for p in products if p["id"] == 1)
    p2 = next(p for p in products if p["id"] == 2)
    expected = p1["price"] + p2["price"]

    r = client.post(
        "/checkout",
        headers=auth(token),
        json={"items": [
            {"product_id": 1, "quantity": 1},
            {"product_id": 2, "quantity": 1},
        ]}
    )
    assert r.status_code == 200
    assert r.json()["total"] == pytest.approx(expected, abs=0.01)


def test_checkout_quantity_multiplier():
    """Checkout with quantity > 1 — total = price * quantity."""
    os.environ["BUG_PRICE"] = "false"
    token = get_token()

    products = client.get("/products").json()
    p4 = next(p for p in products if p["id"] == 4)  # Wireless Mouse 59.99
    expected = p4["price"] * 3

    r = client.post(
        "/checkout",
        headers=auth(token),
        json={"items": [{"product_id": 4, "quantity": 3}]}
    )
    assert r.status_code == 200
    assert r.json()["total"] == pytest.approx(expected, abs=0.01)


def test_checkout_requires_auth():
    """POST /checkout without token must return 401."""
    r = client.post(
        "/checkout",
        json={"items": [{"product_id": 1, "quantity": 1}]}
    )
    assert r.status_code == 401


# ── Orders tests ───────────────────────────────────────────────────────────────

def test_orders_returns_list():
    """GET /orders returns a list (may be empty or have orders from earlier tests)."""
    token = get_token()
    r = client.get("/orders", headers=auth(token))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_orders_after_checkout():
    """After a checkout, orders list should contain at least one entry."""
    os.environ["BUG_PRICE"] = "false"
    token = get_token()
    # Place an order
    client.post(
        "/checkout",
        headers=auth(token),
        json={"items": [{"product_id": 1, "quantity": 1}]}
    )
    r = client.get("/orders", headers=auth(token))
    assert r.status_code == 200
    orders = r.json()
    assert len(orders) >= 1
    order = orders[-1]
    assert "id"    in order
    assert "total" in order


def test_orders_requires_auth():
    """GET /orders without token must return 401."""
    r = client.get("/orders")
    assert r.status_code == 401
