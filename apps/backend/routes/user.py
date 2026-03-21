from fastapi import APIRouter, HTTPException
from typing import Optional
import time

router = APIRouter()


@router.get("/user/profile")
def get_user_profile(user_id: Optional[int] = None):
    """Get user profile information"""
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    # Simulate database lookup
    time.sleep(0.02)

    # Mock user data
    profiles = {
        1: {"id": 1, "name": "John Doe", "email": "john@example.com", "loyalty_points": 150},
        2: {"id": 2, "name": "Jane Smith", "email": "jane@example.com", "loyalty_points": 200},
    }

    profile = profiles.get(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    return profile


@router.get("/user/orders")
def get_user_orders(user_id: Optional[int] = None, limit: int = 10):
    """Get user's order history"""
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    # Simulate database query
    time.sleep(0.03)

    # Mock order data
    mock_orders = [
        {"id": i, "user_id": user_id, "total": 99.99 + i, "status": "completed", "date": f"2024-01-{i:02d}"}
        for i in range(1, limit + 1)
    ]

    return {"orders": mock_orders, "count": len(mock_orders)}


@router.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "shopflow-backend", "version": "2.0.0"}