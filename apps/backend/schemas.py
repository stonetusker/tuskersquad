from pydantic import BaseModel, EmailStr
from typing import List


class LoginRequest(BaseModel):

    email: EmailStr

    password: str


class TokenResponse(BaseModel):

    access_token: str

    token_type: str = "bearer"


class CheckoutItem(BaseModel):

    product_id: int

    quantity: int


class CheckoutRequest(BaseModel):

    items: List[CheckoutItem]


class OrderResponse(BaseModel):

    order_id: int

    total: float
