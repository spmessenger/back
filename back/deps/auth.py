from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.repos.user import User
from core.misc.auth.jwt import JWTTokenManager
from .repos.user import UserRepoDep
from .settings import SecretKeyDep

security = HTTPBearer()


async def aget_current_user(
    repo: UserRepoDep,
    secret_key: SecretKeyDep,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    token_manager = JWTTokenManager(secret_key)
    token = credentials.credentials
    payload = token_manager.verify_token(token)
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
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    token_manager = JWTTokenManager(secret_key)
    token = credentials.credentials

    payload = token_manager.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid or expired token',
            headers={'Authorization': 'Bearer'},
        )

    return repo.get_by_id(payload['id'])


AuthUserDep = Annotated[User, Depends(get_current_user)]
