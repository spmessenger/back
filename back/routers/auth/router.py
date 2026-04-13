from typing import Annotated

from fastapi import APIRouter, Body, Cookie, HTTPException, Response
from pydantic import BaseModel

from back.deps.auth import AuthUserDep
from back.deps.services.auth import AuthServiceDep
from back.deps.services.storage import StorageServiceDep
from back.misc.utils import set_access_token_cookie, set_refresh_token_cookie
from back.schemas import AvatarUpload

router = APIRouter()

AUTH_ERROR_DETAILS = {
    'user_not_found': {'ru': 'User not found', 'en': 'User not found'},
    'user_exists': {'ru': 'User with such username already exists', 'en': 'User with such username already exists'},
    'token_not_found': {'ru': 'Token not found', 'en': 'Token not found'},
    'invalid_avatar': {'ru': 'Incorrect avatar image', 'en': 'Incorrect avatar image'},
    'username_empty': {'ru': 'Username cannot be empty', 'en': 'Username cannot be empty'},
}


class ProfileResponse(BaseModel):
    id: int
    username: str
    avatar_url: str | None = None


class ProfileUpdateRequest(BaseModel):
    username: str | None = None
    avatar: AvatarUpload | None = None


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
        raise HTTPException(status_code=404, detail=AUTH_ERROR_DETAILS['user_not_found']) from e

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
        raise HTTPException(status_code=400, detail=AUTH_ERROR_DETAILS['user_exists']) from e

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
        raise HTTPException(status_code=401, detail=AUTH_ERROR_DETAILS['token_not_found']) from e

    set_access_token_cookie(response, auth)
    set_refresh_token_cookie(response, auth)
    return {'auth': auth}


@router.get('/profile')
def get_profile(user: AuthUserDep) -> ProfileResponse:
    return ProfileResponse(id=user.id, username=user.username, avatar_url=user.avatar_url)


@router.patch('/profile')
def update_profile(
    payload: ProfileUpdateRequest,
    user: AuthUserDep,
    service: AuthServiceDep,
    storage: StorageServiceDep,
) -> ProfileResponse:
    avatar_url = user.avatar_url
    if payload.avatar is not None:
        try:
            avatar_url = storage.render_profile_avatar_data_url(
                data_url=payload.avatar.data_url,
                stage_size=payload.avatar.stage_size,
                crop_x=payload.avatar.crop_x,
                crop_y=payload.avatar.crop_y,
                crop_size=payload.avatar.crop_size,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={**AUTH_ERROR_DETAILS['invalid_avatar'], 'en': str(e)},
            ) from e

    try:
        updated_user = service.update_profile(
            user.id,
            username=payload.username if payload.username is not None else user.username,
            avatar_url=avatar_url,
        )
    except ValueError as e:
        message = str(e)
        if message == 'Username cannot be empty':
            raise HTTPException(
                status_code=400,
                detail={**AUTH_ERROR_DETAILS['username_empty'], 'en': message},
            ) from e

        raise HTTPException(
            status_code=400,
            detail={**AUTH_ERROR_DETAILS['user_exists'], 'en': message},
        ) from e

    return ProfileResponse(
        id=updated_user.id,
        username=updated_user.username,
        avatar_url=updated_user.avatar_url,
    )
