"""
Tests for ShopFlow demo backend API.
Run from the project root:  pytest tests/api/test_backend_checkout.py
"""
from fastapi.testclient import TestClient
from apps.backend.main import app

client = TestClient(app)

# ── Seeded credentials (see apps/backend/seed_data.py) ────────────────────────
DEMO_EMAIL    = "test@example.com"   # exists in seed data
DEMO_PASSWORD = "password"


def get_token() -> str:
    response = client.post(
        "/login",
        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, (
        f"Login failed ({response.status_code}): {response.text}"
    )
    return response.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_login():
    """Valid credentials must return an access token."""
    r = client.post("/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200
    assert "access_token" in r.json()
    assert r.json()["token_type"] == "bearer"


def test_login_wrong_password():
    """Wrong password must return 401."""
    r = client.post("/login", json={"email": DEMO_EMAIL, "password": "wrong"})
    assert r.status_code == 401


def test_products():
    """GET /products must return at least one product."""
    r = client.get("/products")
    assert r.status_code == 200
    products = r.json()
    assert isinstance(products, list)
    assert len(products) > 0
    # Each product must have id, name and price
    for p in products:
        assert "id" in p
        assert "name" in p
        assert "price" in p


def test_product_by_id():
    """GET /products/1 must return the first seeded product."""
    r = client.get("/products/1")
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == 1
    assert "name" in p
    assert "price" in p


def test_product_not_found():
    """GET /products/99999 must return 404."""
    r = client.get("/products/99999")
    assert r.status_code == 404


def test_checkout_price():
    """
    Checkout with product_id=1, quantity=1.
    Expected total = seeded price of the first product.
    Seed: Product 1 is 'Pro Laptop 16\"' at 1299.00.
    """
    import os
    os.environ["BUG_PRICE"] = "false"   # ensure price bug is off

    token = get_token()
    r = client.post(
        "/checkout",
        headers=auth_headers(token),
        json={"items": [{"product_id": 1, "quantity": 1}]}
    )
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "order_id" in data
    # Price must match seeded value exactly (1299.00), not the bugged inflated value
    assert data["total"] == pytest.approx(1299.00, abs=0.01), (
        f"Expected 1299.00 but got {data['total']} — is BUG_PRICE=true?"
    )


def test_checkout_requires_auth():
    """POST /checkout without a token must return 401."""
    r = client.post(
        "/checkout",
        json={"items": [{"product_id": 1, "quantity": 1}]}
    )
    assert r.status_code == 401


def test_checkout_multiple_items():
    """Checkout with multiple items — total must be sum of prices."""
    import os
    os.environ["BUG_PRICE"] = "false"

    token = get_token()
    # Get actual prices first
    products_r = client.get("/products")
    products = products_r.json()
    p1 = next(p for p in products if p["id"] == 1)
    p2 = next(p for p in products if p["id"] == 2)
    expected = p1["price"] + p2["price"]

    r = client.post(
        "/checkout",
        headers=auth_headers(token),
        json={"items": [
            {"product_id": 1, "quantity": 1},
            {"product_id": 2, "quantity": 1},
        ]}
    )
    assert r.status_code == 200
    assert r.json()["total"] == pytest.approx(expected, abs=0.01)


def test_orders():
    """GET /orders must return a list after a checkout."""
    token = get_token()
    r = client.get("/orders", headers=auth_headers(token))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_orders_requires_auth():
    """GET /orders without token must return 401."""
    r = client.get("/orders")
    assert r.status_code == 401


import pytest
