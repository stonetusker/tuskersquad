from fastapi import APIRouter,HTTPException

from apps.backend.schemas import LoginRequest,TokenResponse

from apps.backend.auth import create_access_token


router=APIRouter()


@router.post("/login",response_model=TokenResponse)

def login(data:LoginRequest):

    # demo fake auth

    if data.password!="password":

        raise HTTPException(

            status_code=401,

            detail="Invalid credentials"
        )

    token=create_access_token(

        {"sub":data.email}

    )

    return {

        "access_token":token
    }
