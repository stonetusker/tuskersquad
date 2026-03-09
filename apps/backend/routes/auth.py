from fastapi import APIRouter, HTTPException
from apps.backend.schemas import LoginRequest, TokenResponse
from apps.backend.auth import create_access_token, verify_password
from apps.backend.database import SessionLocal
from apps.backend.models import User

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == data.email).first()
        if not user or not verify_password(data.password, user.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token({"sub": user.email})
        return {"access_token": token, "token_type": "bearer"}
    finally:
        db.close()
