from typing import Annotated, TypeAlias
from fastapi import Depends, HTTPException, status, Cookie, Header
from fastapi.security import HTTPBearer
from core.repos.user import User
from core.misc.auth.jwt import JWTTokenManager
from .repos.user import UserRepoDep
from .settings import SecretKeyDep

security = HTTPBearer()


def _get_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None

    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        return None

    return token


def _verify_access_token(access_token: str | None, secret_key: str) -> dict:
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
    return payload


async def aget_current_user_by_token(
    repo: UserRepoDep,
    secret_key: str,
    access_token: str | None,
) -> User:
    payload = _verify_access_token(access_token=access_token, secret_key=secret_key)
    return await repo.aget_by_id(payload['id'])


def get_current_user_by_token(
    repo: UserRepoDep,
    secret_key: str,
    access_token: str | None,
) -> User:
    payload = _verify_access_token(access_token=access_token, secret_key=secret_key)
    return repo.get_by_id(payload['id'])


async def aget_current_user(
    repo: UserRepoDep,
    secret_key: SecretKeyDep,
    access_token: str | None = Cookie(None),
    authorization: str | None = Header(None),
) -> User:
    return await aget_current_user_by_token(
        repo=repo,
        secret_key=secret_key,
        access_token=access_token or _get_bearer_token(authorization),
    )


def get_current_user(
    repo: UserRepoDep,
    secret_key: SecretKeyDep,
    access_token: str | None = Cookie(None),
    authorization: str | None = Header(None),
) -> User:
    return get_current_user_by_token(
        repo=repo,
        secret_key=secret_key,
        access_token=access_token or _get_bearer_token(authorization),
    )


AuthUserDep: TypeAlias = Annotated[User, Depends(get_current_user)]
