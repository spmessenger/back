from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, Field

from back.deps.auth import AuthUserDep
from back.deps.services.auth import AuthServiceDep
from back.deps.services.storage import StorageServiceDep
from back.misc.utils import set_access_token_cookie, set_refresh_token_cookie
from back.services.youtube_access import list_tier_feature_descriptors, resolve_youtube_access_context_for_user
from back.schemas import AvatarUpload

router = APIRouter()

AUTH_ERROR_DETAILS = {
    'user_not_found': {'ru': 'User not found', 'en': 'User not found'},
    'user_exists': {'ru': 'User with such username already exists', 'en': 'User with such username already exists'},
    'email_exists': {'ru': 'User with such email already exists', 'en': 'User with such email already exists'},
    'invalid_email': {'ru': 'Invalid email', 'en': 'Invalid email'},
    'invalid_verification_code': {'ru': 'Invalid verification code', 'en': 'Invalid verification code'},
    'token_not_found': {'ru': 'Token not found', 'en': 'Token not found'},
    'invalid_avatar': {'ru': 'Incorrect avatar image', 'en': 'Incorrect avatar image'},
    'username_empty': {'ru': 'Username cannot be empty', 'en': 'Username cannot be empty'},
}


class ProfileResponse(BaseModel):
    id: int
    username: str
    avatar_url: str | None = None
    subscription_tier: str = 'free'
    youtube_access_mode: str = 'direct'
    tier_features: list[str] = Field(default_factory=list)
    youtube_assisted_enabled: bool = False
    can_enable_assisted: bool = False


class YouTubeAccessContextResponse(BaseModel):
    subscription_tier: str
    youtube_access_mode: str
    tier_features: list[str]
    youtube_assisted_enabled: bool
    can_enable_assisted: bool


class YouTubeAccessTierResponse(BaseModel):
    tier: str
    features: list[str]


class ProfileUpdateRequest(BaseModel):
    username: str | None = None
    avatar: AvatarUpload | None = None


class MockBillingCompleteRequest(BaseModel):
    tier: str = 'premium'


class YouTubeAssistToggleRequest(BaseModel):
    enabled: bool


class LoginRequest(BaseModel):
    email: str
    verification_code: str


class RegisterRequest(BaseModel):
    email: str
    verification_code: str


@router.post('/login')
def login(
    payload: LoginRequest,
    service: AuthServiceDep,
    response: Response,
):
    try:
        _, auth = service.login(str(payload.email), payload.verification_code)
    except ValueError as e:
        message = str(e)
        if message == 'Incorrect verification code':
            raise HTTPException(status_code=401, detail=AUTH_ERROR_DETAILS['invalid_verification_code']) from e
        if message == 'Invalid email':
            raise HTTPException(status_code=400, detail=AUTH_ERROR_DETAILS['invalid_email']) from e
        raise HTTPException(status_code=404, detail=AUTH_ERROR_DETAILS['user_not_found']) from e

    set_access_token_cookie(response, auth)
    set_refresh_token_cookie(response, auth)
    return {'auth': auth}


@router.post('/register')
async def register(
    payload: RegisterRequest,
    service: AuthServiceDep,
    response: Response,
):
    try:
        _, private_chat, auth = service.register(str(payload.email), payload.verification_code)
    except ValueError as e:
        message = str(e)
        if message == 'Incorrect verification code':
            raise HTTPException(status_code=401, detail=AUTH_ERROR_DETAILS['invalid_verification_code']) from e
        if message == 'Invalid email':
            raise HTTPException(status_code=400, detail=AUTH_ERROR_DETAILS['invalid_email']) from e
        raise HTTPException(status_code=400, detail=AUTH_ERROR_DETAILS['email_exists']) from e

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
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return ProfileResponse(
        id=user.id,
        username=user.username,
        avatar_url=user.avatar_url,
        subscription_tier=access_context.subscription_tier,
        youtube_access_mode=access_context.youtube_access_mode,
        tier_features=list(access_context.tier_features),
        youtube_assisted_enabled=access_context.youtube_assisted_enabled,
        can_enable_assisted=access_context.can_enable_assisted,
    )


@router.get('/youtube-access/context')
def get_youtube_access_context(user: AuthUserDep) -> YouTubeAccessContextResponse:
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return YouTubeAccessContextResponse(
        subscription_tier=access_context.subscription_tier,
        youtube_access_mode=access_context.youtube_access_mode,
        tier_features=list(access_context.tier_features),
        youtube_assisted_enabled=access_context.youtube_assisted_enabled,
        can_enable_assisted=access_context.can_enable_assisted,
    )


@router.post('/youtube-access/assisted-toggle')
def set_youtube_assisted_toggle(
    payload: YouTubeAssistToggleRequest,
    user: AuthUserDep,
    service: AuthServiceDep,
) -> YouTubeAccessContextResponse:
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    if not access_context.can_enable_assisted:
        if payload.enabled:
            raise HTTPException(
                status_code=403,
                detail={
                    'en': 'Assisted mode is available for premium tier when feature is enabled',
                    'ru': 'Режим assisting доступен только для premium при включенной функции',
                },
            )
        # Keep explicitly disabled state persisted for consistency.
        updated_user = service.set_youtube_assisted_enabled(user.id, False)
    else:
        updated_user = service.set_youtube_assisted_enabled(user.id, payload.enabled)

    updated_access_context = resolve_youtube_access_context_for_user(
        username=updated_user.username,
        persisted_tier=updated_user.subscription_tier,
        persisted_youtube_assisted_enabled=updated_user.youtube_assisted_enabled,
    )
    return YouTubeAccessContextResponse(
        subscription_tier=updated_access_context.subscription_tier,
        youtube_access_mode=updated_access_context.youtube_access_mode,
        tier_features=list(updated_access_context.tier_features),
        youtube_assisted_enabled=updated_access_context.youtube_assisted_enabled,
        can_enable_assisted=updated_access_context.can_enable_assisted,
    )


@router.get('/youtube-access/tiers')
def get_youtube_access_tiers() -> list[YouTubeAccessTierResponse]:
    return [
        YouTubeAccessTierResponse(tier=descriptor.tier, features=list(descriptor.features))
        for descriptor in list_tier_feature_descriptors()
    ]


@router.post('/billing/mock/complete')
def complete_mock_billing(
    payload: MockBillingCompleteRequest,
    user: AuthUserDep,
    service: AuthServiceDep,
) -> ProfileResponse:
    try:
        updated_user = service.set_subscription_tier(user.id, payload.tier)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={'en': str(e), 'ru': 'Unsupported subscription tier'}) from e

    access_context = resolve_youtube_access_context_for_user(
        username=updated_user.username,
        persisted_tier=updated_user.subscription_tier,
        persisted_youtube_assisted_enabled=updated_user.youtube_assisted_enabled,
    )
    return ProfileResponse(
        id=updated_user.id,
        username=updated_user.username,
        avatar_url=updated_user.avatar_url,
        subscription_tier=access_context.subscription_tier,
        youtube_access_mode=access_context.youtube_access_mode,
        tier_features=list(access_context.tier_features),
        youtube_assisted_enabled=access_context.youtube_assisted_enabled,
        can_enable_assisted=access_context.can_enable_assisted,
    )


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

    access_context = resolve_youtube_access_context_for_user(
        username=updated_user.username,
        persisted_tier=updated_user.subscription_tier,
        persisted_youtube_assisted_enabled=updated_user.youtube_assisted_enabled,
    )
    return ProfileResponse(
        id=updated_user.id,
        username=updated_user.username,
        avatar_url=updated_user.avatar_url,
        subscription_tier=access_context.subscription_tier,
        youtube_access_mode=access_context.youtube_access_mode,
        tier_features=list(access_context.tier_features),
        youtube_assisted_enabled=access_context.youtube_assisted_enabled,
        can_enable_assisted=access_context.can_enable_assisted,
    )
