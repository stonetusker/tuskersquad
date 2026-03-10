from fastapi import APIRouter, Query
from typing import List, Optional
import time

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


@router.get("/products/search")
def search_products(q: str = Query(..., description="Search query")):
    """Search products by name"""
    # Simulate search delay for testing
    time.sleep(0.1)

    db = SessionLocal()
    products = db.query(Product).filter(Product.name.ilike(f"%{q}%")).all()
    result = [
        {
            "id": p.id,
            "name": p.name,
            "price": p.price,
        }
        for p in products
    ]
    db.close()
    return {"query": q, "results": result, "count": len(result)}


@router.get("/products/{product_id}")
def get_product(product_id: int):
    """Get single product by ID"""
    db = SessionLocal()
    product = db.query(Product).filter(Product.id == product_id).first()
    db.close()

    if not product:
        return {"error": "Product not found"}, 404

    return {
        "id": product.id,
        "name": product.name,
        "price": product.price,
    }


@router.get("/products/recommendations")
def get_recommendations(user_id: Optional[int] = None, limit: int = 5):
    """Get product recommendations"""
    # Simulate recommendation logic
    time.sleep(0.05)

    db = SessionLocal()
    products = db.query(Product).limit(limit).all()
    result = [
        {
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "recommended_for": f"user_{user_id}" if user_id else "anonymous"
        }
        for p in products
    ]
    db.close()
    return {"recommendations": result}
