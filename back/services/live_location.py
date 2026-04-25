from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass
class LiveLocationShare:
    chat_id: int
    user_id: int
    username: str
    avatar_url: str | None
    latitude: float
    longitude: float
    accuracy_meters: float | None
    started_at: float
    updated_at: float
    expires_at: float | None


class LiveLocationService:
    _shares_by_chat_and_user: dict[tuple[int, int], LiveLocationShare] = {}

    def upsert_share(
        self,
        *,
        chat_id: int,
        user_id: int,
        username: str,
        avatar_url: str | None,
        latitude: float,
        longitude: float,
        accuracy_meters: float | None,
        expires_at: float | None,
    ) -> LiveLocationShare:
        key = (chat_id, user_id)
        now = time.time()
        existing = self._shares_by_chat_and_user.get(key)
        started_at = existing.started_at if existing is not None else now
        share = LiveLocationShare(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            avatar_url=avatar_url,
            latitude=float(latitude),
            longitude=float(longitude),
            accuracy_meters=float(accuracy_meters) if accuracy_meters is not None else None,
            started_at=started_at,
            updated_at=now,
            expires_at=expires_at,
        )
        self._shares_by_chat_and_user[key] = share
        return share

    def update_share(
        self,
        *,
        chat_id: int,
        user_id: int,
        latitude: float,
        longitude: float,
        accuracy_meters: float | None,
    ) -> LiveLocationShare:
        key = (chat_id, user_id)
        share = self._shares_by_chat_and_user.get(key)
        if share is None:
            raise ValueError('Live location share is not active')

        share.latitude = float(latitude)
        share.longitude = float(longitude)
        share.accuracy_meters = float(accuracy_meters) if accuracy_meters is not None else None
        share.updated_at = time.time()
        self._shares_by_chat_and_user[key] = share
        return share

    def stop_share(self, *, chat_id: int, user_id: int) -> LiveLocationShare | None:
        return self._shares_by_chat_and_user.pop((chat_id, user_id), None)

    def stop_all_for_user(self, *, user_id: int) -> list[LiveLocationShare]:
        removed: list[LiveLocationShare] = []
        for key in list(self._shares_by_chat_and_user.keys()):
            chat_id, share_user_id = key
            if share_user_id != user_id:
                continue
            removed_share = self._shares_by_chat_and_user.pop((chat_id, share_user_id), None)
            if removed_share is not None:
                removed.append(removed_share)
        return removed

    def list_chat_shares(self, *, chat_id: int) -> list[LiveLocationShare]:
        return [
            share
            for (share_chat_id, _), share in self._shares_by_chat_and_user.items()
            if share_chat_id == chat_id
        ]

    def pop_expired_shares(self, *, chat_id: int, now: float | None = None) -> list[LiveLocationShare]:
        resolved_now = time.time() if now is None else now
        expired: list[LiveLocationShare] = []
        for key in list(self._shares_by_chat_and_user.keys()):
            share_chat_id, _ = key
            if share_chat_id != chat_id:
                continue
            share = self._shares_by_chat_and_user.get(key)
            if share is None:
                continue
            if share.expires_at is None:
                continue
            if share.expires_at > resolved_now:
                continue
            removed_share = self._shares_by_chat_and_user.pop(key, None)
            if removed_share is not None:
                expired.append(removed_share)
        return expired
