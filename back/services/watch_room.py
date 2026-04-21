from __future__ import annotations

from dataclasses import dataclass
import time
from uuid import uuid4


@dataclass
class WatchRoom:
    id: str
    chat_id: int
    youtube_video_id: str
    host_user_id: int
    viewer_user_ids: set[int]
    sync_revision: int
    sync_current_time_seconds: float
    sync_is_playing: bool
    created_at: float


@dataclass
class WatchRoomInvite:
    id: str
    room_id: str
    from_user_id: int
    from_username: str
    to_user_id: int
    source_chat_id: int
    target_chat_id: int | None
    youtube_video_id: str
    status: str
    created_at: float


class WatchRoomService:
    _rooms: dict[str, WatchRoom] = {}
    _rooms_by_chat_and_video: dict[tuple[int, str], str] = {}
    _invites: dict[str, WatchRoomInvite] = {}

    def find_room(self, *, chat_id: int, youtube_video_id: str) -> WatchRoom | None:
        room_id = self._rooms_by_chat_and_video.get((chat_id, youtube_video_id))
        if room_id is None:
            return None
        return self._rooms.get(room_id)

    def get_room(self, room_id: str) -> WatchRoom:
        room = self._rooms.get(room_id)
        if room is None:
            raise ValueError('Room not found')
        return room

    def has_room(self, room_id: str) -> bool:
        return room_id in self._rooms

    def create_or_get_room(self, *, chat_id: int, youtube_video_id: str, host_user_id: int) -> WatchRoom:
        existing = self.find_room(chat_id=chat_id, youtube_video_id=youtube_video_id)
        if existing is not None:
            existing.viewer_user_ids.add(host_user_id)
            self._rooms[existing.id] = existing
            return existing

        room = WatchRoom(
            id=uuid4().hex,
            chat_id=chat_id,
            youtube_video_id=youtube_video_id,
            host_user_id=host_user_id,
            viewer_user_ids={host_user_id},
            sync_revision=0,
            sync_current_time_seconds=0.0,
            sync_is_playing=True,
            created_at=time.time(),
        )
        self._rooms[room.id] = room
        self._rooms_by_chat_and_video[(chat_id, youtube_video_id)] = room.id
        return room

    def join_room(self, *, room_id: str, user_id: int) -> WatchRoom:
        room = self.get_room(room_id)
        room.viewer_user_ids.add(user_id)
        self._rooms[room.id] = room
        return room

    def leave_room(self, *, room_id: str, user_id: int) -> WatchRoom:
        room = self.get_room(room_id)
        room.viewer_user_ids.discard(user_id)
        if not room.viewer_user_ids:
            self._rooms.pop(room.id, None)
            self._rooms_by_chat_and_video.pop((room.chat_id, room.youtube_video_id), None)
            return room

        if room.host_user_id == user_id:
            room.host_user_id = next(iter(room.viewer_user_ids))
        self._rooms[room.id] = room
        return room

    def sync_room(self, *, room_id: str, current_time_seconds: float, is_playing: bool) -> WatchRoom:
        room = self.get_room(room_id)
        room.sync_revision += 1
        room.sync_current_time_seconds = max(0.0, float(current_time_seconds))
        room.sync_is_playing = bool(is_playing)
        self._rooms[room.id] = room
        return room

    def create_invite(
        self,
        *,
        room_id: str,
        from_user_id: int,
        from_username: str,
        to_user_id: int,
        source_chat_id: int,
        target_chat_id: int | None,
        youtube_video_id: str,
    ) -> WatchRoomInvite:
        invite = WatchRoomInvite(
            id=uuid4().hex,
            room_id=room_id,
            from_user_id=from_user_id,
            from_username=from_username,
            to_user_id=to_user_id,
            source_chat_id=source_chat_id,
            target_chat_id=target_chat_id,
            youtube_video_id=youtube_video_id,
            status='pending',
            created_at=time.time(),
        )
        self._invites[invite.id] = invite
        return invite

    def get_invite(self, invite_id: str) -> WatchRoomInvite:
        invite = self._invites.get(invite_id)
        if invite is None:
            raise ValueError('Invite not found')
        return invite

    def find_pending_invites_for_user(self, user_id: int) -> list[WatchRoomInvite]:
        return [
            invite
            for invite in self._invites.values()
            if invite.to_user_id == user_id and invite.status == 'pending'
        ]

    def accept_invite(self, invite_id: str, user_id: int) -> WatchRoomInvite:
        invite = self.get_invite(invite_id)
        if invite.to_user_id != user_id:
            raise ValueError('Invite does not belong to user')
        invite.status = 'accepted'
        self._invites[invite.id] = invite
        self.join_room(room_id=invite.room_id, user_id=user_id)
        return invite

    def decline_invite(self, invite_id: str, user_id: int) -> WatchRoomInvite:
        invite = self.get_invite(invite_id)
        if invite.to_user_id != user_id:
            raise ValueError('Invite does not belong to user')
        invite.status = 'declined'
        self._invites[invite.id] = invite
        return invite
