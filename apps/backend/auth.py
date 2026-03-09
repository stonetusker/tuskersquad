"""
Auth helpers for ShopFlow demo app.
Uses bcrypt directly — no passlib dependency.
"""
from datetime import datetime, timedelta
import bcrypt
from jose import jwt

SECRET_KEY  = "tuskersquad-demo-secret-key-2024"
ALGORITHM   = "HS256"
TOKEN_EXPIRY = 240  # 4 hours — convenient for demos


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRY)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
