from fastapi import APIRouter, Depends
from apps.backend.database import SessionLocal
from apps.backend.models import Order
from apps.backend.dependencies import get_current_user

router = APIRouter()


@router.get("/orders")
def get_orders(user=Depends(get_current_user)):
    db = SessionLocal()
    try:
        orders = db.query(Order).filter(Order.user_id == 1).all()
        return [{"id": o.id, "total": o.total, "user_id": o.user_id} for o in orders]
    finally:
        db.close()
