from fastapi import Depends,HTTPException
from fastapi.security import OAuth2PasswordBearer

from jose import jwt,JWTError

from apps.backend.auth import SECRET_KEY,ALGORITHM

from apps.backend.bug_flags import BUG_SECURITY


oauth2_scheme=OAuth2PasswordBearer(

    tokenUrl="login"
)


def get_current_user(

    token:str=Depends(oauth2_scheme)

):

    try:

        payload=jwt.decode(

            token,

            SECRET_KEY,

            algorithms=[ALGORITHM]

        )

        user_id=payload.get("sub")

        if user_id is None:

            raise HTTPException(

                status_code=401,

                detail="Invalid token"
            )

        return user_id

    except JWTError:

        # ⭐ intentional bug

        if BUG_SECURITY:

            # bypass auth

            return "anonymous"

        raise HTTPException(

            status_code=401,

            detail="Unauthorized"
        )
