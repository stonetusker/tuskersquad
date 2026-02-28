from fastapi.testclient import TestClient

from apps.backend.main import app


client = TestClient(app)


def get_token():

    response = client.post(

        "/login",

        json={

            "email": "demo@test.com",

            "password": "password"

        }

    )

    assert response.status_code == 200

    return response.json()["access_token"]


def test_products():

    r = client.get("/products")

    assert r.status_code == 200

    assert len(r.json()) > 0


def test_checkout_price():

    token = get_token()

    r = client.post(

        "/checkout",

        headers={

            "Authorization": f"Bearer {token}"

        },

        json={

            "items":[

                {

                    "product_id":1,

                    "quantity":1

                }

            ]

        }

    )

    assert r.status_code == 200

    data = r.json()

    # Laptop price expected

    expected_price = 1000

    assert data["total"] == expected_price


def test_orders():

    token = get_token()

    r = client.get(

        "/orders",

        headers={

            "Authorization": f"Bearer {token}"

        }

    )

    assert r.status_code == 200
