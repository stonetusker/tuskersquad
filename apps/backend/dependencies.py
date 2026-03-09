from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from apps.backend.auth import SECRET_KEY, ALGORITHM
from apps.backend.bug_flags import BUG_SECURITY

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except JWTError:
        if BUG_SECURITY:
            return "anonymous"          # ⭐ intentional auth-bypass bug
        raise HTTPException(status_code=401, detail="Unauthorized")
