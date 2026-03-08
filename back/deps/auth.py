from typing import Annotated, TypeAlias
from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import HTTPBearer
from core.repos.user import User
from core.misc.auth.jwt import JWTTokenManager
from .repos.user import UserRepoDep
from .settings import SecretKeyDep

security = HTTPBearer()


async def aget_current_user(
    repo: UserRepoDep,
    secret_key: SecretKeyDep,
    access_token: str | None = Cookie(None),
) -> User:
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Access token is missing'
        )
    token_manager = JWTTokenManager(secret_key)
    payload = token_manager.verify_token(access_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid or expired token',
            headers={'Authorization': 'Bearer'},
        )
    return await repo.aget_by_id(payload['id'])


def get_current_user(
    repo: UserRepoDep,
    secret_key: SecretKeyDep,
    access_token: str | None = Cookie(None),
) -> User:
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Access token is missing'
        )
    token_manager = JWTTokenManager(secret_key)
    payload = token_manager.verify_token(access_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid or expired token',
            headers={'Authorization': 'Bearer'},
        )

    return repo.get_by_id(payload['id'])


AuthUserDep: TypeAlias = Annotated[User, Depends(get_current_user)]
