from __future__ import annotations
import json
import ipaddress
import re
from html import unescape
from urllib.parse import quote, unquote, urlparse
import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError
from core.entities.chat import Chat
from core.entities.chat_group import ChatGroup
from back.deps.auth import AuthUserDep, get_current_user_by_token
from back.deps.settings import SecretKeyDep
from back.deps.repos.chat import ChatRepoDep
from back.deps.repos.user import UserRepoDep
from back.deps.services.messenger import MessengerServiceDep
from back.deps.services.watch_room import WatchRoomServiceDep
from back.services.ws_manager import WebSocketConnectionManager
from back.deps.services.storage import StorageServiceDep
from .schemas import (
    AttachmentCompleteRequest,
    AttachmentCompleteResponse,
    AttachmentDownloadResponse,
    AttachmentInitRequest,
    AttachmentInitResponse,
    AvailableUser,
    ChatCreation,
    ChatAttachmentResponse,
    ChatGroupResponse,
    ChatMessageResponse,
    GroupCreationRequest,
    LinkPreviewResponse,
    WatchRoomCreateRequest,
    WatchRoomInviteRequest,
    WatchRoomInviteResponse,
    WatchRoomResponse,
    WatchRoomSyncRequest,
    ReplaceChatGroupsRequest,
    SendMessageRequest,
    WsChatActionRequest,
)

router = APIRouter(tags=['Chats'])
ATTACHMENT_CONTENT_PREFIX = '__attachment_v1__:'
META_TAG_RE = re.compile(r'<meta[^>]+>', re.IGNORECASE)
ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*([\'"])(.*?)\2')
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)


def _serialize_content_value(
    content: str,
) -> tuple[str, str, ChatAttachmentResponse | None, str | None, str | None]:
    if not content.startswith(ATTACHMENT_CONTENT_PREFIX):
        return content, 'text', None, None, None

    payload_raw = content[len(ATTACHMENT_CONTENT_PREFIX):]
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return content, 'text', None, None, None

    storage_key = payload.get('storage_key')
    if not storage_key:
        storage_key = _extract_storage_key_from_download_url(payload.get('download_url'))

    attachment = ChatAttachmentResponse(
        id=payload.get('attachment_id', ''),
        original_name=payload.get('original_name', 'attachment'),
        mime_type=payload.get('mime_type', 'application/octet-stream'),
        size_bytes=int(payload.get('size_bytes', 0) or 0),
        download_url=payload.get('download_url'),
        status=payload.get('status', 'ready'),
    )
    content_type = payload.get('content_type', 'document')
    caption = payload.get('caption', '')
    attachment_group_id = payload.get('attachment_group_id')

    return caption, content_type, attachment, storage_key, attachment_group_id


def _serialize_message(message, own_participant_id: int) -> ChatMessageResponse:
    content, content_type, attachment, storage_key, attachment_group_id = _serialize_content_value(message.content)
    if attachment is not None:
        attachment.download_url = _resolve_attachment_download_url(
            chat_id=message.chat_id,
            attachment_id=attachment.id,
            storage_key=storage_key,
            local_path=None,
            storage=None,
        )
    return ChatMessageResponse(
        id=message.id,
        chat_id=message.chat_id,
        reference_message_id=message.reference_message_id,
        reference_author=message.reference_author,
        reference_content=message.reference_content,
        forwarded_from_message_id=message.forwarded_from_message_id,
        forwarded_from_author=message.forwarded_from_author,
        forwarded_from_author_avatar_url=message.forwarded_from_author_avatar_url,
        forwarded_from_content=message.forwarded_from_content,
        content=content,
        content_type=content_type,  # type: ignore[arg-type]
        attachment=attachment,
        attachment_group_id=attachment_group_id,
        created_at_timestamp=float(message.created_at_timestamp),
        is_own=message.participant_id == own_participant_id,
    )


def _make_attachment_content(
    *,
    attachment_id: str,
    original_name: str,
    mime_type: str,
    size_bytes: int,
    download_url: str,
    storage_key: str,
    attachment_group_id: str | None,
    content_type: str,
    caption: str,
) -> str:
    payload = {
        'attachment_id': attachment_id,
        'original_name': original_name,
        'mime_type': mime_type,
        'size_bytes': size_bytes,
        'download_url': download_url,
        'storage_key': storage_key,
        'attachment_group_id': attachment_group_id,
        'status': 'ready',
        'content_type': content_type,
        'caption': caption,
    }
    return f'{ATTACHMENT_CONTENT_PREFIX}{json.dumps(payload)}'


def _resolve_attachment_download_url(
    *,
    chat_id: int,
    attachment_id: str,
    storage_key: str | None,
    local_path: str | None,
    storage: StorageServiceDep | None,
) -> str:
    if local_path is not None:
        return f'/api/chats/{chat_id}/attachments/{attachment_id}/content'
    base_path = f'/api/chats/{chat_id}/attachments/{attachment_id}/content'
    if storage_key:
        return f'{base_path}?key={quote(storage_key, safe="")}'
    return base_path


def _extract_storage_key_from_download_url(download_url: str | None) -> str | None:
    if not download_url:
        return None
    try:
        parsed = urlparse(download_url)
    except ValueError:
        return None

    path = unquote(parsed.path or '')
    if not path:
        return None

    trimmed_path = path.lstrip('/')
    if not trimmed_path:
        return None
    if '/' not in trimmed_path:
        return None

    _, key = trimmed_path.split('/', 1)
    return key or None


def _normalize_external_url(raw_value: str) -> str:
    normalized = raw_value.strip()
    if not normalized:
        raise ValueError('URL is empty')
    if not normalized.startswith(('http://', 'https://')):
        normalized = f'https://{normalized}'

    parsed = urlparse(normalized)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('Only absolute HTTP/HTTPS URLs are allowed')
    return normalized


def _is_forbidden_preview_host(host: str) -> bool:
    host_lower = host.lower().strip().strip('[]')
    if not host_lower:
        return True
    if host_lower in {'localhost', '127.0.0.1', '0.0.0.0', '::1'}:
        return True
    if host_lower.endswith('.local'):
        return True
    try:
        parsed_ip = ipaddress.ip_address(host_lower)
    except ValueError:
        return False
    return (
        parsed_ip.is_private or
        parsed_ip.is_loopback or
        parsed_ip.is_link_local or
        parsed_ip.is_multicast or
        parsed_ip.is_reserved
    )


def _extract_meta_value(html_text: str, attr_name: str, attr_value: str) -> str | None:
    for match in META_TAG_RE.finditer(html_text):
        tag = match.group(0)
        attrs = {
            key.lower(): unescape(value).strip()
            for key, _, value in ATTR_RE.findall(tag)
        }
        if attrs.get(attr_name) == attr_value:
            content = attrs.get('content')
            if content:
                return content
    return None


def _extract_title(html_text: str) -> str | None:
    title_match = TITLE_RE.search(html_text)
    if title_match is None:
        return None
    title = unescape(title_match.group(1)).strip()
    return title or None


def _extract_youtube_video_id(url_value: str) -> str | None:
    parsed = urlparse(url_value)
    host = parsed.hostname.lower().replace('www.', '') if parsed.hostname else ''
    if host == 'youtu.be':
        path_parts = [part for part in parsed.path.split('/') if part]
        return path_parts[0] if path_parts else None
    if host in {'youtube.com', 'm.youtube.com'}:
        if parsed.path == '/watch':
            query = parsed.query
            for pair in query.split('&'):
                if pair.startswith('v='):
                    return pair[2:] or None
        path_parts = [part for part in parsed.path.split('/') if part]
        if len(path_parts) >= 2 and path_parts[0] in {'shorts', 'embed'}:
            return path_parts[1]
    return None


def _resolve_chat_last_message_preview(last_message: str | None) -> str | None:
    if last_message is None:
        return None

    caption, content_type, attachment, _, _ = _serialize_content_value(last_message)
    if attachment is None:
        return last_message

    trimmed_caption = caption.strip()
    if trimmed_caption:
        return trimmed_caption

    if content_type == 'image':
        return 'Photo'
    if content_type == 'video':
        return 'Video'
    return 'Document'


def _serialize_watch_room(room) -> WatchRoomResponse:
    viewer_ids = sorted(room.viewer_user_ids)
    return WatchRoomResponse(
        id=room.id,
        chat_id=room.chat_id,
        youtube_video_id=room.youtube_video_id,
        host_user_id=room.host_user_id,
        viewer_user_ids=viewer_ids,
        viewer_count=len(viewer_ids),
        sync_revision=room.sync_revision,
        sync_current_time_seconds=room.sync_current_time_seconds,
        sync_is_playing=room.sync_is_playing,
        created_at=room.created_at,
    )


def _serialize_watch_room_invite(invite) -> WatchRoomInviteResponse:
    return WatchRoomInviteResponse(
        id=invite.id,
        room_id=invite.room_id,
        from_user_id=invite.from_user_id,
        from_username=invite.from_username,
        to_user_id=invite.to_user_id,
        source_chat_id=invite.source_chat_id,
        target_chat_id=invite.target_chat_id,
        youtube_video_id=invite.youtube_video_id,
        status=invite.status,  # type: ignore[arg-type]
        created_at=invite.created_at,
    )


@router.get('/available-users')
async def get_available_users(
    user: AuthUserDep,
    user_repo: UserRepoDep,
) -> list[AvailableUser]:
    users = user_repo.find_all()
    return [
        AvailableUser(
            id=registered_user.id,
            username=registered_user.username,
            avatar_url=registered_user.avatar_url,
        )
        for registered_user in users
        if registered_user.id != user.id
    ]


@router.get('/chats')
async def get_chats(
    user: AuthUserDep,
    chat_repo: ChatRepoDep,
) -> list[Chat]:
    chats = chat_repo.find_all(user_id=user.id)
    return [
        chat.model_copy(
            update={'last_message': _resolve_chat_last_message_preview(chat.last_message)},
        )
        for chat in chats
    ]


@router.get('/chat-groups')
async def get_chat_groups(
    user: AuthUserDep,
    messenger: MessengerServiceDep,
) -> list[ChatGroupResponse]:
    groups = messenger.get_chat_groups(user_id=user.id)
    return [
        ChatGroupResponse(id=group.id, title=group.title, chat_ids=group.chat_ids)
        for group in groups
    ]


@router.get('/link-preview')
async def get_link_preview(
    _: AuthUserDep,
    url: str = Query(...),
) -> LinkPreviewResponse:
    try:
        normalized_url = _normalize_external_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parsed = urlparse(normalized_url)
    host = parsed.hostname or ''
    if _is_forbidden_preview_host(host):
        raise HTTPException(status_code=400, detail='Preview is not allowed for this host')

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
            response = await client.get(
                normalized_url,
                headers={'User-Agent': 'spmessenger-link-preview/1.0'},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail='Failed to fetch URL preview') from exc

    html_text = response.text[:300000]
    youtube_video_id = _extract_youtube_video_id(str(response.url))

    title = (
        _extract_meta_value(html_text, 'property', 'og:title') or
        _extract_meta_value(html_text, 'name', 'twitter:title') or
        _extract_title(html_text)
    )
    description = (
        _extract_meta_value(html_text, 'property', 'og:description') or
        _extract_meta_value(html_text, 'name', 'description') or
        _extract_meta_value(html_text, 'name', 'twitter:description')
    )
    image_url = (
        _extract_meta_value(html_text, 'property', 'og:image') or
        _extract_meta_value(html_text, 'name', 'twitter:image')
    )
    site_name = _extract_meta_value(html_text, 'property', 'og:site_name') or host

    return LinkPreviewResponse(
        url=str(response.url),
        title=title,
        description=description,
        image_url=image_url,
        site_name=site_name,
        youtube_video_id=youtube_video_id,
    )


async def _broadcast_watch_room_update(
    *,
    request: Request,
    messenger: MessengerServiceDep,
    room,
) -> None:
    ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
    participants = messenger.get_chat_participants(chat_id=room.chat_id)
    recipients = {participant.user_id for participant in participants}
    recipients.update(room.viewer_user_ids)
    payload = {
        'type': 'watch_room_updated',
        'room': _serialize_watch_room(room).model_dump(),
    }
    for user_id in recipients:
        await ws_manager.send_to_user(user_id=user_id, payload=payload)


def _can_access_watch_room(room, user_id: int, messenger: MessengerServiceDep) -> bool:
    if user_id in room.viewer_user_ids:
        return True
    try:
        messenger.get_chat_participant(chat_id=room.chat_id, user_id=user_id)
        return True
    except ValueError:
        return False


@router.post('/watch-rooms')
async def create_watch_room(
    request: Request,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
    payload: WatchRoomCreateRequest = Body(),
) -> WatchRoomResponse:
    messenger.get_chat_participant(chat_id=payload.chat_id, user_id=user.id)
    room = watch_rooms.create_or_get_room(
        chat_id=payload.chat_id,
        youtube_video_id=payload.youtube_video_id,
        host_user_id=user.id,
    )
    await _broadcast_watch_room_update(request=request, messenger=messenger, room=room)
    return _serialize_watch_room(room)


@router.get('/watch-rooms/by-chat/{chat_id}')
async def get_watch_room_by_chat(
    chat_id: int,
    youtube_video_id: str,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
) -> WatchRoomResponse:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    room = watch_rooms.find_room(chat_id=chat_id, youtube_video_id=youtube_video_id)
    if room is None:
        raise HTTPException(status_code=404, detail='Room not found')
    return _serialize_watch_room(room)


@router.get('/watch-rooms/room/{room_id}')
async def get_watch_room(
    room_id: str,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
) -> WatchRoomResponse:
    room = watch_rooms.get_room(room_id)
    if not _can_access_watch_room(room, user.id, messenger):
        raise HTTPException(status_code=403, detail='Access denied')
    return _serialize_watch_room(room)


@router.post('/watch-rooms/{room_id}/join')
async def join_watch_room(
    room_id: str,
    request: Request,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
) -> WatchRoomResponse:
    room = watch_rooms.get_room(room_id)
    if not _can_access_watch_room(room, user.id, messenger):
        raise HTTPException(status_code=403, detail='Access denied')
    room = watch_rooms.join_room(room_id=room_id, user_id=user.id)
    await _broadcast_watch_room_update(request=request, messenger=messenger, room=room)
    return _serialize_watch_room(room)


@router.post('/watch-rooms/{room_id}/leave')
async def leave_watch_room(
    room_id: str,
    request: Request,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
) -> WatchRoomResponse:
    room = watch_rooms.get_room(room_id)
    if not _can_access_watch_room(room, user.id, messenger):
        raise HTTPException(status_code=403, detail='Access denied')
    room = watch_rooms.leave_room(room_id=room_id, user_id=user.id)
    if watch_rooms.has_room(room.id):
        await _broadcast_watch_room_update(request=request, messenger=messenger, room=room)
    return _serialize_watch_room(room)


@router.post('/watch-rooms/{room_id}/sync')
async def sync_watch_room(
    room_id: str,
    request: Request,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
    payload: WatchRoomSyncRequest = Body(),
) -> WatchRoomResponse:
    room = watch_rooms.get_room(room_id)
    if not _can_access_watch_room(room, user.id, messenger):
        raise HTTPException(status_code=403, detail='Access denied')
    room = watch_rooms.sync_room(
        room_id=room_id,
        current_time_seconds=payload.current_time_seconds,
        is_playing=payload.is_playing,
    )
    await _broadcast_watch_room_update(request=request, messenger=messenger, room=room)
    return _serialize_watch_room(room)


@router.post('/watch-rooms/{room_id}/invite')
async def invite_to_watch_room(
    room_id: str,
    request: Request,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
    payload: WatchRoomInviteRequest = Body(),
) -> WatchRoomInviteResponse:
    room = watch_rooms.get_room(room_id)
    messenger.get_chat_participant(chat_id=room.chat_id, user_id=user.id)
    if payload.target_chat_id is not None:
        messenger.get_chat_participant(chat_id=payload.target_chat_id, user_id=user.id)
        try:
            messenger.get_chat_participant(chat_id=payload.target_chat_id, user_id=payload.target_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail='Target user is not in target chat') from exc

    invite = watch_rooms.create_invite(
        room_id=room_id,
        from_user_id=user.id,
        from_username=user.username,
        to_user_id=payload.target_user_id,
        source_chat_id=room.chat_id,
        target_chat_id=payload.target_chat_id,
        youtube_video_id=room.youtube_video_id,
    )

    ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
    await ws_manager.send_to_user(
        user_id=payload.target_user_id,
        payload={
            'type': 'watch_room_invite',
            'invite': _serialize_watch_room_invite(invite).model_dump(),
        },
    )
    return _serialize_watch_room_invite(invite)


@router.get('/watch-rooms/invites')
async def get_watch_room_invites(
    user: AuthUserDep,
    watch_rooms: WatchRoomServiceDep,
) -> list[WatchRoomInviteResponse]:
    invites = watch_rooms.find_pending_invites_for_user(user_id=user.id)
    return [_serialize_watch_room_invite(invite) for invite in invites]


@router.post('/watch-rooms/invites/{invite_id}/accept')
async def accept_watch_room_invite(
    invite_id: str,
    request: Request,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
) -> WatchRoomResponse:
    invite = watch_rooms.accept_invite(invite_id=invite_id, user_id=user.id)
    room = watch_rooms.get_room(invite.room_id)
    await _broadcast_watch_room_update(request=request, messenger=messenger, room=room)
    return _serialize_watch_room(room)


@router.post('/watch-rooms/invites/{invite_id}/decline')
async def decline_watch_room_invite(
    invite_id: str,
    user: AuthUserDep,
    watch_rooms: WatchRoomServiceDep,
) -> WatchRoomInviteResponse:
    invite = watch_rooms.decline_invite(invite_id=invite_id, user_id=user.id)
    return _serialize_watch_room_invite(invite)


@router.put('/chat-groups')
async def replace_chat_groups(
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    payload: ReplaceChatGroupsRequest = Body(),
) -> list[ChatGroupResponse]:
    try:
        groups = messenger.replace_chat_groups(
            user_id=user.id,
            groups=[
                ChatGroup.Creation(
                    user_id=user.id,
                    title=group.title,
                    chat_ids=group.chat_ids,
                )
                for group in payload.groups
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [
        ChatGroupResponse(id=group.id, title=group.title, chat_ids=group.chat_ids)
        for group in groups
    ]


@router.post('/chats/dialog')
async def create_dialog(
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    participant_id: int = Body(..., embed=True),
) -> ChatCreation:
    chat, participants = messenger.create_dialog(user.id, participant_id)
    return ChatCreation(chat=chat, participants=participants)


@router.post('/chats/group')
async def create_group(
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    storage: StorageServiceDep,
    request: Request,
    payload: GroupCreationRequest = Body(),
) -> ChatCreation:
    avatar_url: str | None = None
    if payload.avatar is not None:
        avatar_url = storage.render_group_avatar_data_url(
            data_url=payload.avatar.data_url,
            stage_size=payload.avatar.stage_size,
            crop_x=payload.avatar.crop_x,
            crop_y=payload.avatar.crop_y,
            crop_size=payload.avatar.crop_size,
        )

    chat, participants = messenger.create_group_chat(
        user.id, payload.title, payload.participants, avatar_url)

    ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
    for participant in participants:
        if participant.user_id == user.id:
            continue
        await ws_manager.send_to_user(
            user_id=participant.user_id,
            payload={
                'type': 'chat_created',
                'chat_id': chat.id,
            },
        )

    return ChatCreation(chat=chat, participants=participants)


@router.get('/chats/{chat_id}/messages')
async def get_chat_messages(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
) -> list[ChatMessageResponse]:
    participant, messages = messenger.get_chat_messages(chat_id=chat_id, user_id=user.id)
    return [_serialize_message(message, participant.id) for message in messages]


@router.post('/chats/{chat_id}/attachments/init')
async def init_chat_attachment(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    storage: StorageServiceDep,
    payload: AttachmentInitRequest = Body(),
) -> AttachmentInitResponse:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    try:
        result = storage.init_attachment_upload(
            chat_id=chat_id,
            filename=payload.filename,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result['upload_url'] = f'/api/chats/{chat_id}/attachments/{result["attachment_id"]}/upload'
    result['upload_method'] = 'PUT'
    result['headers'] = {'Content-Type': payload.mime_type}
    return AttachmentInitResponse(**result)


@router.put('/chats/{chat_id}/attachments/{attachment_id}/upload', status_code=204)
async def upload_chat_attachment(
    chat_id: int,
    attachment_id: str,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    storage: StorageServiceDep,
    request: Request,
    content_type: str | None = Header(default=None),
) -> Response:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    record = storage.get_attachment_record(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Attachment not found')

    if f'chat-attachments/{chat_id}/' not in record.storage_key:
        raise HTTPException(status_code=403, detail='Attachment does not belong to chat')

    body = await request.body()
    try:
        storage.upload_attachment_content(
            attachment_id=attachment_id,
            content=body,
            content_type=content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Response(status_code=204)


@router.post('/chats/{chat_id}/attachments/{attachment_id}/complete')
async def complete_chat_attachment(
    chat_id: int,
    attachment_id: str,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    storage: StorageServiceDep,
    payload: AttachmentCompleteRequest = Body(),
) -> AttachmentCompleteResponse:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    _ = payload  # reserved for future checksum verification
    try:
        record = storage.complete_attachment_upload(attachment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if f'chat-attachments/{chat_id}/' not in record.storage_key:
        raise HTTPException(status_code=403, detail='Attachment does not belong to chat')

    return AttachmentCompleteResponse(
        attachment_id=record.attachment_id,
        status=record.status,  # type: ignore[arg-type]
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
    )


@router.get('/chats/{chat_id}/attachments/{attachment_id}/download')
async def get_chat_attachment_download_url(
    chat_id: int,
    attachment_id: str,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    storage: StorageServiceDep,
) -> AttachmentDownloadResponse:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    record = storage.get_attachment_record(attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Attachment not found')

    if f'chat-attachments/{chat_id}/' not in record.storage_key:
        raise HTTPException(status_code=403, detail='Attachment does not belong to chat')

    url = _resolve_attachment_download_url(
        chat_id=chat_id,
        attachment_id=attachment_id,
        storage_key=record.storage_key,
        local_path=record.local_path,
        storage=storage,
    )
    return AttachmentDownloadResponse(url=url, expires_in=300)


@router.get('/chats/{chat_id}/attachments/{attachment_id}/content')
async def get_chat_attachment_content(
    chat_id: int,
    attachment_id: str,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    storage: StorageServiceDep,
    key: str | None = Query(default=None),
) -> Response:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    record = storage.get_attachment_record(attachment_id)
    if record is not None:
        if f'chat-attachments/{chat_id}/' not in record.storage_key:
            raise HTTPException(status_code=403, detail='Attachment does not belong to chat')
        if record.local_path is not None:
            return FileResponse(
                path=record.local_path,
                media_type=record.mime_type or 'application/octet-stream',
                filename=record.original_name,
            )

        presigned_url = storage.generate_attachment_download_url(storage_key=record.storage_key)
        return RedirectResponse(url=presigned_url, status_code=307)

    if key is None:
        raise HTTPException(status_code=404, detail='Attachment not found')
    resolved_key = unquote(key)
    if not resolved_key.startswith(f'chat-attachments/{chat_id}/'):
        raise HTTPException(status_code=403, detail='Attachment does not belong to chat')

    presigned_url = storage.generate_attachment_download_url(storage_key=resolved_key)
    return RedirectResponse(url=presigned_url, status_code=307)


@router.post('/chats/{chat_id}/messages')
async def send_chat_message(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    storage: StorageServiceDep,
    payload: SendMessageRequest = Body(),
) -> ChatMessageResponse:
    participant = messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    content = payload.content
    if payload.attachment_id is not None:
        record = storage.get_attachment_record(payload.attachment_id)
        if record is None:
            raise HTTPException(status_code=400, detail='Attachment not found')
        if record.status != 'ready':
            raise HTTPException(status_code=400, detail='Attachment is not ready')
        if f'chat-attachments/{chat_id}/' not in record.storage_key:
            raise HTTPException(status_code=403, detail='Attachment does not belong to chat')

        download_url = _resolve_attachment_download_url(
            chat_id=chat_id,
            attachment_id=record.attachment_id,
            storage_key=record.storage_key,
            local_path=record.local_path,
            storage=storage,
        )
        content = _make_attachment_content(
            attachment_id=record.attachment_id,
            original_name=record.original_name,
            mime_type=record.mime_type,
            size_bytes=record.size_bytes,
            download_url=download_url,
            storage_key=record.storage_key,
            attachment_group_id=payload.attachment_group_id,
            content_type=payload.content_type or 'document',
            caption=payload.content,
        )

    try:
        message = messenger.send_message(
            chat_id,
            user.id,
            content,
            reference_message_id=payload.reference_message_id,
            forwarded_from_message_id=payload.forwarded_from_message_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_message(message, participant.id)


@router.post('/chats/{chat_id}/pin')
async def pin_chat(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
) -> bool:
    return messenger.pin_chat(chat_id=chat_id, user_id=user.id)


@router.post('/chats/{chat_id}/unpin')
async def unpin_chat(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
) -> bool:
    return messenger.unpin_chat(chat_id=chat_id, user_id=user.id)


@router.websocket('/ws/chats')
async def chats_socket(
    websocket: WebSocket,
    user_repo: UserRepoDep,
    secret_key: SecretKeyDep,
    messenger: MessengerServiceDep,
):
    access_token = websocket.cookies.get('access_token')
    try:
        user = get_current_user_by_token(
            repo=user_repo,
            secret_key=secret_key,
            access_token=access_token,
        )
    except HTTPException:
        await websocket.close(code=1008)
        return

    ws_manager: WebSocketConnectionManager = websocket.app.state.ws_manager
    await ws_manager.connect(user_id=user.id, websocket=websocket)

    try:
        while True:
            payload = await websocket.receive_json()
            try:
                request = WsChatActionRequest.model_validate(payload)
            except ValidationError as validation_error:
                await websocket.send_json(
                    {
                        'type': 'error',
                        'detail': str(validation_error),
                    }
                )
                continue

            try:
                if request.action == 'get_messages':
                    participant, messages, has_more = messenger.get_chat_messages_page(
                        chat_id=request.chat_id,
                        user_id=user.id,
                        before_message_id=request.before_message_id,
                        limit=request.limit or 50,
                    )
                    await websocket.send_json(
                        {
                            'type': 'messages',
                            'chat_id': request.chat_id,
                            'has_more': has_more,
                            'request_before_message_id': request.before_message_id,
                            'messages': [
                                _serialize_message(message, participant.id).model_dump()
                                for message in messages
                            ],
                        }
                    )
                    continue

                sent_message = messenger.send_message(
                    chat_id=request.chat_id,
                    sender_id=user.id,
                    content=request.content or '',
                    reference_message_id=request.reference_message_id,
                    forwarded_from_message_id=request.forwarded_from_message_id,
                )
                sender_participant = messenger.get_chat_participant(
                    chat_id=request.chat_id,
                    user_id=user.id,
                )
                sender_message = _serialize_message(
                    sent_message,
                    sender_participant.id,
                ).model_dump()
                sender_message['client_message_id'] = request.client_message_id
                await websocket.send_json(
                    {
                        'type': 'message',
                        'message': sender_message,
                    }
                )

                participants = messenger.get_chat_participants(chat_id=request.chat_id)
                for participant in participants:
                    if participant.user_id == user.id:
                        continue

                    serialized_message = _serialize_message(
                        sent_message,
                        participant.id,
                    ).model_dump()

                    await ws_manager.send_to_user(
                        user_id=participant.user_id,
                        payload={
                            'type': 'message',
                            'message': serialized_message,
                        },
                    )
            except Exception as exc:
                await websocket.send_json(
                    {
                        'type': 'error',
                        'chat_id': request.chat_id,
                        'detail': str(exc),
                    }
                )
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id=user.id, websocket=websocket)
