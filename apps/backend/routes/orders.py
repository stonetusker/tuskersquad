from fastapi import APIRouter, Depends

from apps.backend.database import SessionLocal

from apps.backend.models import Order

from apps.backend.dependencies import get_current_user


router = APIRouter()


@router.get("/orders")

def orders(

    user=Depends(get_current_user)

):

    db = SessionLocal()

    orders = db.query(Order).all()

    result = [

        {

            "id": o.id,

            "total": o.total

        }

        for o in orders

    ]

    db.close()

    return result
