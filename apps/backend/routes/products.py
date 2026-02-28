from fastapi import APIRouter

from apps.backend.database import SessionLocal
from apps.backend.models import Product


router = APIRouter()


@router.get("/products")

def get_products():

    db = SessionLocal()

    products = db.query(Product).all()

    result = [

        {
            "id": p.id,
            "name": p.name,
            "price": p.price,
        }

        for p in products

    ]

    db.close()

    return result
