import time

from fastapi import APIRouter, Depends

from apps.backend.schemas import CheckoutRequest, OrderResponse

from apps.backend.database import SessionLocal

from apps.backend.models import Product, Order

from apps.backend.dependencies import get_current_user

from apps.backend.bug_flags import BUG_PRICE, BUG_SLOW


router = APIRouter()


@router.post("/checkout", response_model=OrderResponse)

def checkout(

    request: CheckoutRequest,

    user = Depends(get_current_user)

):

    # artificial performance bug

    if BUG_SLOW:

        time.sleep(3)

    db = SessionLocal()

    total = 0

    for item in request.items:

        product = (

            db.query(Product)

            .filter(Product.id == item.product_id)

            .first()

        )

        if product:

            total += product.price * item.quantity

    # ⭐ intentional pricing defect

    if BUG_PRICE:

        total = total * 1.35

    order = Order(

        user_id=1,

        total=total

    )

    db.add(order)

    db.commit()

    db.refresh(order)

    db.close()

    return OrderResponse(

        order_id=order.id,

        total=total

    )
