from dataclasses import dataclass

from back.settings import get_settings

settings = get_settings()

TierName = str

TIER_FEATURES: dict[TierName, tuple[str, ...]] = {
    'free': (
        'watch_room_basic',
        'youtube_direct_playback',
    ),
    'premium': (
        'watch_room_basic',
        'youtube_direct_playback',
        'youtube_assisted_access',
        'watch_room_network_assist_priority',
    ),
}


@dataclass(frozen=True)
class YouTubeAccessContext:
    subscription_tier: str
    youtube_access_mode: str
    tier_features: tuple[str, ...]
    youtube_assisted_enabled: bool
    can_enable_assisted: bool


@dataclass(frozen=True)
class TierFeaturesDescriptor:
    tier: str
    features: tuple[str, ...]


def _parse_premium_usernames(raw_value: str) -> set[str]:
    return {item.strip().lower() for item in raw_value.split(',') if item.strip()}


def _resolve_tier_for_user(*, username: str, persisted_tier: str | None) -> str:
    normalized_persisted = (persisted_tier or '').strip().lower()
    if normalized_persisted in TIER_FEATURES:
        return normalized_persisted

    premium_usernames = _parse_premium_usernames(settings.YOUTUBE_ASSISTED_PREMIUM_USERNAMES)
    return 'premium' if username.strip().lower() in premium_usernames else 'free'


def list_tier_feature_descriptors() -> tuple[TierFeaturesDescriptor, ...]:
    return tuple(
        TierFeaturesDescriptor(tier=tier, features=features)
        for tier, features in TIER_FEATURES.items()
    )


def resolve_youtube_access_context_for_user(
    *,
    username: str,
    persisted_tier: str | None = None,
    persisted_youtube_assisted_enabled: bool | None = None,
) -> YouTubeAccessContext:
    subscription_tier = _resolve_tier_for_user(username=username, persisted_tier=persisted_tier)
    features = TIER_FEATURES.get(subscription_tier, TIER_FEATURES['free'])
    can_enable_assisted = (
        subscription_tier == 'premium'
        and settings.YOUTUBE_ASSISTED_FEATURE_ENABLED
        and 'youtube_assisted_access' in features
    )
    youtube_assisted_enabled = bool(persisted_youtube_assisted_enabled) if can_enable_assisted else False
    youtube_access_mode = (
        'assisted' if youtube_assisted_enabled else 'direct'
    )
    return YouTubeAccessContext(
        subscription_tier=subscription_tier,
        youtube_access_mode=youtube_access_mode,
        tier_features=features,
        youtube_assisted_enabled=youtube_assisted_enabled,
        can_enable_assisted=can_enable_assisted,
    )


def resolve_youtube_access_context_for_tier(*, tier: str) -> YouTubeAccessContext:
    normalized_tier = tier.strip().lower()
    subscription_tier = normalized_tier if normalized_tier in TIER_FEATURES else 'free'
    features = TIER_FEATURES[subscription_tier]
    can_enable_assisted = (
        subscription_tier == 'premium'
        and settings.YOUTUBE_ASSISTED_FEATURE_ENABLED
        and 'youtube_assisted_access' in features
    )
    youtube_assisted_enabled = can_enable_assisted
    youtube_access_mode = 'assisted' if youtube_assisted_enabled else 'direct'
    return YouTubeAccessContext(
        subscription_tier=subscription_tier,
        youtube_access_mode=youtube_access_mode,
        tier_features=features,
        youtube_assisted_enabled=youtube_assisted_enabled,
        can_enable_assisted=can_enable_assisted,
    )
