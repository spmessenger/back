from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Body, Cookie, HTTPException, Response
from back.deps.services.auth import AuthServiceDep
from back.misc.utils import set_access_token_cookie, set_refresh_token_cookie

router = APIRouter()


@router.post('/login')
def login(
    username: Annotated[str, Body(embed=False)],
    password: Annotated[str, Body(embed=False)],
    service: AuthServiceDep,
    response: Response,
):
    try:
        _, auth = service.login(username, password)
    except ValueError as e:
        raise HTTPException(status_code=404, detail={'ru': 'Пользователь не найден', 'en': 'User not found'}) from e
    set_access_token_cookie(response, auth)
    set_refresh_token_cookie(response, auth)
    return {'auth': auth}


@router.post('/register')
async def register(
    username: Annotated[str, Body(embed=False)],
    password: Annotated[str, Body(embed=False)],
    service: AuthServiceDep,
    response: Response,
):
    try:
        _, private_chat, auth = service.register(username, password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={
                            'ru': 'Пользователь с таким именем уже существует', 'en': 'User with such username already exists'}) from e
    set_access_token_cookie(response, auth)
    set_refresh_token_cookie(response, auth)
    return {'auth': auth, 'chats': [private_chat]}


@router.post('/refresh')
async def refresh(
    service: AuthServiceDep,
    response: Response,
    refresh_token: str = Cookie(),
):
    try:
        auth = service.refresh_token(refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail={'ru': 'Токен не найден', 'en': 'Token not found'}) from e
    set_access_token_cookie(response, auth)
    set_refresh_token_cookie(response, auth)
    return {'auth': auth}
