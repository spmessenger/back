from __future__ import annotations
import json
import ipaddress
import re
import time
from html import unescape
from urllib.parse import quote, unquote, urlencode, urljoin, urlparse
import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import ValidationError
from core.entities.chat import Chat
from core.entities.chat_group import ChatGroup
from back.deps.auth import AuthUserDep, get_current_user_by_token
from back.deps.settings import SecretKeyDep
from back.deps.repos.chat import ChatRepoDep
from back.deps.repos.user import UserRepoDep
from back.deps.services.messenger import MessengerServiceDep
from back.deps.services.watch_room import WatchRoomServiceDep
from back.deps.services.expense_split import ExpenseSplitServiceDep
from back.deps.services.live_location import LiveLocationServiceDep
from back.settings import get_settings
from back.services.ws_manager import WebSocketConnectionManager
from back.services.youtube_access import resolve_youtube_access_context_for_user
from back.deps.services.storage import StorageServiceDep
from .schemas import (
    AttachmentCompleteRequest,
    AttachmentCompleteResponse,
    AttachmentDownloadResponse,
    AttachmentInitRequest,
    AttachmentInitResponse,
    AvailableUser,
    ExpenseBalanceResponse,
    ExpenseCreateRequest,
    ExpenseMarkPaidRequest,
    ExpenseOverviewResponse,
    ExpensePaymentResponse,
    ExpenseParticipantShareResponse,
    ExpenseResponse,
    ExpenseSettlementResponse,
    ChatCreation,
    ChatAttachmentResponse,
    ChatGroupResponse,
    ChatMessageResponse,
    ChatMessageDeleteResponse,
    GroupCreationRequest,
    LinkPreviewResponse,
    WatchRoomCreateRequest,
    WatchRoomInviteRequest,
    WatchRoomInviteResponse,
    WatchRoomResponse,
    WatchRoomChatMessageResponse,
    WatchRoomViewerSyncStateResponse,
    WatchRoomSyncRequest,
    ReplaceChatGroupsRequest,
    SendMessageRequest,
    WsChatActionRequest,
)

back_settings = get_settings()
router = APIRouter(tags=['Chats'])
ATTACHMENT_CONTENT_PREFIX = '__attachment_v1__:'
META_TAG_RE = re.compile(r'<meta[^>]+>', re.IGNORECASE)
ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*([\'"])(.*?)\2')
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)
ABSOLUTE_URL_RE = re.compile(r'https?://[^\s"\'<>]+', re.IGNORECASE)
PROTOCOL_RELATIVE_URL_RE = re.compile(
    r'(?P<prefix>["\'(=,:\s])//(?P<host>[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?P<path>/[^\s"\'<>]*)?')
ROOT_RELATIVE_ATTR_RE = re.compile(
    r'(?P<quote>["\'])/(?P<path>(?!/)[^"\']+)(?P=quote)')
ASSIST_TEXT_CONTENT_TYPES = (
    'text/html',
)


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
        storage_key = _extract_storage_key_from_download_url(
            payload.get('download_url'))

    duration_ms_raw = payload.get('duration_ms')
    try:
        duration_ms = int(
            duration_ms_raw) if duration_ms_raw is not None else None
    except (TypeError, ValueError):
        duration_ms = None

    duration_seconds_raw = payload.get('duration_seconds')
    try:
        duration_seconds = (
            float(duration_seconds_raw)
            if duration_seconds_raw is not None
            else (duration_ms / 1000 if duration_ms is not None else None)
        )
    except (TypeError, ValueError):
        duration_seconds = None

    attachment = ChatAttachmentResponse(
        id=payload.get('attachment_id', ''),
        original_name=payload.get('original_name', 'attachment'),
        mime_type=payload.get('mime_type', 'application/octet-stream'),
        size_bytes=int(payload.get('size_bytes', 0) or 0),
        download_url=payload.get('download_url'),
        status=payload.get('status', 'ready'),
        duration_ms=duration_ms,
        duration_seconds=duration_seconds,
    )
    content_type = payload.get('content_type', 'document')
    caption = payload.get('caption', '')
    attachment_group_id = payload.get('attachment_group_id')

    return caption, content_type, attachment, storage_key, attachment_group_id


def _serialize_message(message, own_participant_id: int) -> ChatMessageResponse:
    content, content_type, attachment, storage_key, attachment_group_id = _serialize_content_value(
        message.content)
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
    duration_ms: int | None = None,
    duration_seconds: float | None = None,
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
        'duration_ms': duration_ms,
        'duration_seconds': duration_seconds,
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


def _normalize_assist_tunnel_url(raw_value: str) -> str:
    normalized = raw_value.strip()
    if not normalized:
        raise ValueError('URL is empty')

    # Handle protocol-relative and relative chunks produced by JS runtime links.
    if normalized.startswith('//'):
        normalized = f'https:{normalized}'
    elif normalized.startswith('/'):
        normalized = f'https://www.youtube.com{normalized}'
    elif not normalized.startswith(('http://', 'https://')):
        if '/' in normalized and '.' not in normalized.split('/', 1)[0]:
            normalized = f'https://www.youtube.com/{normalized.lstrip("/")}'
        else:
            normalized = f'https://{normalized}'

    try:
        parsed = urlparse(normalized)
    except ValueError as exc:
        raise ValueError('Invalid URL format') from exc

    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('Only absolute HTTP/HTTPS URLs are allowed')
    return normalized


def _parse_assist_allowed_hosts(raw_value: str) -> tuple[str, ...]:
    return tuple(
        host.strip().lower()
        for host in raw_value.split(',')
        if host.strip()
    )


def _is_allowed_assist_host(host: str | None) -> bool:
    if not host:
        return False
    host_lower = host.strip().lower()
    if not host_lower:
        return False
    allowed_hosts = _parse_assist_allowed_hosts(
        back_settings.YOUTUBE_ASSIST_PROXY_ALLOWED_HOSTS)
    return any(host_lower == allowed or host_lower.endswith(f'.{allowed}') for allowed in allowed_hosts)


def _is_assist_text_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    normalized_content_type = content_type.lower()
    return any(media_type in normalized_content_type for media_type in ASSIST_TEXT_CONTENT_TYPES)


def _build_assist_tunnel_url(raw_url: str) -> str:
    return f'/api/youtube/assist/tunnel?url={quote(raw_url, safe="")}'


def _ensure_assisted_enabled_for_user(user: AuthUserDep) -> None:
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    if access_context.youtube_access_mode != 'assisted':
        raise HTTPException(
            status_code=403,
            detail='Assisted transport is available only when assisted mode is enabled',
        )


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

    caption, content_type, attachment, _, _ = _serialize_content_value(
        last_message)
    if attachment is None:
        return last_message

    trimmed_caption = caption.strip()
    if trimmed_caption:
        return trimmed_caption

    if content_type == 'image':
        return 'Photo'
    if content_type == 'video':
        return 'Video'
    if content_type == 'voice':
        return 'Voice message'
    return 'Document'


def _serialize_watch_room(room, *, youtube_access_mode: str = 'direct') -> WatchRoomResponse:
    viewer_ids = sorted(room.viewer_user_ids)
    viewer_sync_states = [
        WatchRoomViewerSyncStateResponse(
            user_id=user_id,
            current_time_seconds=current_time_seconds,
            is_playing=is_playing,
            updated_at=updated_at,
        )
        for user_id, (current_time_seconds, is_playing, updated_at) in sorted(room.viewer_sync_states.items())
    ]
    return WatchRoomResponse(
        id=room.id,
        chat_id=room.chat_id,
        youtube_video_id=room.youtube_video_id,
        youtube_access_mode=youtube_access_mode,  # type: ignore[arg-type]
        host_user_id=room.host_user_id,
        viewer_user_ids=viewer_ids,
        viewer_count=len(viewer_ids),
        sync_revision=room.sync_revision,
        sync_current_time_seconds=room.sync_current_time_seconds,
        sync_is_playing=room.sync_is_playing,
        viewer_sync_states=viewer_sync_states,
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


def _serialize_watch_room_chat_message(message) -> WatchRoomChatMessageResponse:
    return WatchRoomChatMessageResponse(
        id=message.id,
        room_id=message.room_id,
        user_id=message.user_id,
        username=message.username,
        content=message.content,
        created_at=message.created_at,
    )


def _serialize_message_deleted(*, chat_id: int, message_id: int) -> ChatMessageDeleteResponse:
    return ChatMessageDeleteResponse(chat_id=chat_id, message_id=message_id)


def _serialize_live_location_share(share) -> dict:
    return {
        'chat_id': share.chat_id,
        'user_id': share.user_id,
        'username': share.username,
        'avatar_url': share.avatar_url,
        'latitude': share.latitude,
        'longitude': share.longitude,
        'accuracy_meters': share.accuracy_meters,
        'started_at': share.started_at,
        'updated_at': share.updated_at,
        'expires_at': share.expires_at,
    }


def _serialize_expense(expense) -> ExpenseResponse:
    shares = [
        ExpenseParticipantShareResponse(
            user_id=user_id, share_minor=share_minor)
        for user_id, share_minor in sorted(expense.shares_minor_by_user_id.items())
    ]
    return ExpenseResponse(
        id=expense.id,
        chat_id=expense.chat_id,
        title=expense.title,
        amount_minor=expense.amount_minor,
        currency=expense.currency,
        payer_user_id=expense.payer_user_id,
        created_by_user_id=expense.created_by_user_id,
        created_at=expense.created_at,
        shares=shares,
    )


def _build_expense_overview(*, chat_id: int, expenses: ExpenseSplitServiceDep) -> ExpenseOverviewResponse:
    chat_expenses = expenses.list_expenses(chat_id=chat_id)
    currency = chat_expenses[0].currency if chat_expenses else 'RUB'
    balances = [
        ExpenseBalanceResponse(user_id=user_id, balance_minor=balance_minor)
        for user_id, balance_minor in sorted(expenses.compute_balances(chat_id=chat_id).items())
    ]
    settlements = [
        ExpenseSettlementResponse(
            from_user_id=settlement.from_user_id,
            to_user_id=settlement.to_user_id,
            amount_minor=settlement.amount_minor,
        )
        for settlement in expenses.compute_outstanding_settlements(chat_id=chat_id)
    ]

    return ExpenseOverviewResponse(
        chat_id=chat_id,
        currency=currency,
        total_expenses_minor=expenses.total_expenses_minor(chat_id=chat_id),
        balances=balances,
        settlements=settlements,
        open_expense_count=len(chat_expenses),
    )


def _serialize_expense_payment(payment) -> ExpensePaymentResponse:
    return ExpensePaymentResponse(
        id=payment.id,
        chat_id=payment.chat_id,
        from_user_id=payment.from_user_id,
        to_user_id=payment.to_user_id,
        amount_minor=payment.amount_minor,
        created_by_user_id=payment.created_by_user_id,
        created_at=payment.created_at,
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
            update={'last_message': _resolve_chat_last_message_preview(
                chat.last_message)},
        )
        for chat in chats
    ]


@router.get('/chats/{chat_id}/participants')
async def get_chat_participants(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    user_repo: UserRepoDep,
) -> list[AvailableUser]:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    participants = messenger.get_chat_participants(chat_id=chat_id)
    users = {
        registered_user.id: registered_user for registered_user in user_repo.find_all()}
    result: list[AvailableUser] = []
    for participant in participants:
        participant_user = users.get(participant.user_id)
        if participant_user is None:
            continue
        result.append(
            AvailableUser(
                id=participant_user.id,
                username=participant_user.username,
                avatar_url=participant_user.avatar_url,
            )
        )
    return result


@router.post('/chats/{chat_id}/expenses')
async def create_chat_expense(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    expenses: ExpenseSplitServiceDep,
    payload: ExpenseCreateRequest = Body(),
) -> ExpenseResponse:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    for participant_user_id in payload.participant_user_ids:
        messenger.get_chat_participant(
            chat_id=chat_id, user_id=participant_user_id)
    messenger.get_chat_participant(
        chat_id=chat_id, user_id=payload.payer_user_id)

    shares_minor_by_user_id: dict[int, int] | None = None
    if payload.shares_minor is not None:
        shares_minor_by_user_id = {
            item.user_id: item.share_minor
            for item in payload.shares_minor
        }

    try:
        expense = expenses.create_expense(
            chat_id=chat_id,
            title=payload.title,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            payer_user_id=payload.payer_user_id,
            created_by_user_id=user.id,
            participant_user_ids=payload.participant_user_ids,
            shares_minor_by_user_id=shares_minor_by_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _serialize_expense(expense)


@router.get('/chats/{chat_id}/expenses')
async def get_chat_expenses(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    expenses: ExpenseSplitServiceDep,
) -> list[ExpenseResponse]:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    return [
        _serialize_expense(expense)
        for expense in expenses.list_expenses(chat_id=chat_id)
    ]


@router.get('/chats/{chat_id}/expenses/payments')
async def get_chat_expense_payments(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    expenses: ExpenseSplitServiceDep,
) -> list[ExpensePaymentResponse]:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    return [
        _serialize_expense_payment(payment)
        for payment in expenses.list_payments(chat_id=chat_id)
    ]


@router.get('/chats/{chat_id}/expenses/overview')
async def get_chat_expense_overview(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    expenses: ExpenseSplitServiceDep,
) -> ExpenseOverviewResponse:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    return _build_expense_overview(chat_id=chat_id, expenses=expenses)


@router.post('/chats/{chat_id}/expenses/settlements/mark-paid')
async def mark_chat_expense_settlement_paid(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    expenses: ExpenseSplitServiceDep,
    payload: ExpenseMarkPaidRequest = Body(),
) -> ExpenseOverviewResponse:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    messenger.get_chat_participant(
        chat_id=chat_id, user_id=payload.from_user_id)
    messenger.get_chat_participant(chat_id=chat_id, user_id=payload.to_user_id)
    try:
        expenses.mark_settlement_paid(
            chat_id=chat_id,
            from_user_id=payload.from_user_id,
            to_user_id=payload.to_user_id,
            amount_minor=payload.amount_minor,
            created_by_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_expense_overview(chat_id=chat_id, expenses=expenses)


@router.get('/chat-groups')
async def get_chat_groups(
    user: AuthUserDep,
    messenger: MessengerServiceDep,
) -> list[ChatGroupResponse]:
    groups = messenger.get_chat_groups(user_id=user.id)
    return [
        ChatGroupResponse(
            id=group.id,
            title=group.title,
            chat_ids=group.chat_ids,
            unread_messages_count=group.unread_messages_count,
        )
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
        raise HTTPException(
            status_code=400, detail='Preview is not allowed for this host')

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
            response = await client.get(
                normalized_url,
                headers={'User-Agent': 'spmessenger-link-preview/1.0'},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=400, detail='Failed to fetch URL preview') from exc

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
    site_name = _extract_meta_value(
        html_text, 'property', 'og:site_name') or host

    return LinkPreviewResponse(
        url=str(response.url),
        title=title,
        description=description,
        image_url=image_url,
        site_name=site_name,
        youtube_video_id=youtube_video_id,
    )


@router.get('/youtube/assist/embed/{video_id}')
async def get_youtube_assist_embed(
    video_id: str,
    request: Request,
    user: AuthUserDep,
) -> RedirectResponse:
    _ensure_assisted_enabled_for_user(user)
    query_params = dict(request.query_params)
    query_params.setdefault('autoplay', '0')
    query_params.setdefault('rel', '0')
    query_params.setdefault('playsinline', '1')
    query_params.setdefault('enablejsapi', '0')
    request_origin = request.headers.get('origin')
    if request_origin:
        query_params.setdefault('origin', request_origin)
    target_url = f'https://www.youtube.com/embed/{quote(video_id, safe="")}'
    if query_params:
        target_url = f'{target_url}?{urlencode(query_params)}'
    return RedirectResponse(url=_build_assist_tunnel_url(target_url), status_code=307)


@router.api_route('/youtube/assist/tunnel', methods=['GET', 'POST', 'HEAD', 'OPTIONS'])
async def tunnel_youtube_assist_resource(
    request: Request,
    user: AuthUserDep,
    url: str = Query(...),
    range_header: str | None = Header(default=None, alias='Range'),
) -> Response:
    _ensure_assisted_enabled_for_user(user)
    try:
        normalized_url = _normalize_assist_tunnel_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        parsed_url = urlparse(normalized_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail='Invalid URL format') from exc
    if not parsed_url.hostname:
        raise HTTPException(status_code=400, detail='Invalid URL host')
    if not _is_allowed_assist_host(parsed_url.hostname):
        raise HTTPException(
            status_code=403, detail='Host is not allowed for assisted tunnel')

    request_headers: dict[str, str] = {
        'User-Agent': request.headers.get('user-agent', 'spmessenger-youtube-assist/1.0'),
        'Accept': request.headers.get('accept', '*/*'),
    }
    if range_header:
        request_headers['Range'] = range_header
    for header_name in (
        'content-type',
        'origin',
        'referer',
        'accept-language',
        'x-youtube-client-name',
        'x-youtube-client-version',
        'x-goog-visitor-id',
        'x-goog-authuser',
        'authorization',
    ):
        header_value = request.headers.get(header_name)
        if header_value:
            request_headers[header_name] = header_value

    client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=back_settings.YOUTUBE_ASSIST_PROXY_TIMEOUT_SECONDS,
    )
    try:
        request_content: bytes | None = None
        if request.method in {'POST', 'PUT', 'PATCH'}:
            request_content = await request.body()
        request_obj = client.build_request(
            request.method,
            normalized_url,
            headers=request_headers,
            content=request_content,
        )
        upstream_response = await client.send(request_obj, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502, detail='Failed to fetch upstream resource') from exc

    upstream_content_type = upstream_response.headers.get(
        'content-type', 'application/octet-stream')
    forwarded_headers: dict[str, str] = {}
    for header_name in ('cache-control', 'etag', 'last-modified', 'accept-ranges', 'content-range'):
        header_value = upstream_response.headers.get(header_name)
        if header_value:
            forwarded_headers[header_name] = header_value

    forwarded_headers['x-assisted-proxy'] = 'spmessenger'
    forwarded_headers['x-assisted-target-host'] = parsed_url.hostname or ''

    if _is_assist_text_content_type(upstream_content_type):
        payload_bytes = await upstream_response.aread()
        await upstream_response.aclose()
        await client.aclose()
        source_text = payload_bytes.decode(
            upstream_response.encoding or 'utf-8', errors='ignore')
        rewritten_text = _rewrite_assist_proxy_text_payload(
            source_text,
            base_url=str(upstream_response.url),
        )
        forwarded_headers['content-type'] = upstream_content_type
        return Response(
            content=rewritten_text,
            status_code=upstream_response.status_code,
            headers=forwarded_headers,
        )

    async def stream_upstream_bytes():
        try:
            async for chunk in upstream_response.aiter_bytes():
                yield chunk
        finally:
            await upstream_response.aclose()
            await client.aclose()

    forwarded_headers['content-type'] = upstream_content_type
    return StreamingResponse(
        stream_upstream_bytes(),
        status_code=upstream_response.status_code,
        headers=forwarded_headers,
    )


async def _broadcast_watch_room_update(
    *,
    request: Request | WebSocket,
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


async def _broadcast_watch_room_chat_message(
    *,
    request: Request | WebSocket,
    messenger: MessengerServiceDep,
    room,
    message,
) -> None:
    ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
    participants = messenger.get_chat_participants(chat_id=room.chat_id)
    recipients = {participant.user_id for participant in participants}
    recipients.update(room.viewer_user_ids)
    payload = {
        'type': 'watch_room_chat_message',
        'message': _serialize_watch_room_chat_message(message).model_dump(),
    }
    for user_id in recipients:
        await ws_manager.send_to_user(user_id=user_id, payload=payload)


async def _broadcast_message_deleted(
    *,
    request: Request | WebSocket,
    messenger: MessengerServiceDep,
    chat_id: int,
    message_id: int,
) -> None:
    ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
    participants = messenger.get_chat_participants(chat_id=chat_id)
    payload = {
        'type': 'message_deleted',
        'chat_id': chat_id,
        'message_id': message_id,
    }
    for participant in participants:
        await ws_manager.send_to_user(user_id=participant.user_id, payload=payload)


async def _broadcast_live_location_update(
    *,
    request: Request | WebSocket,
    messenger: MessengerServiceDep,
    share,
) -> None:
    ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
    participants = messenger.get_chat_participants(chat_id=share.chat_id)
    payload = {
        'type': 'live_location_updated',
        'share': _serialize_live_location_share(share),
    }
    for participant in participants:
        await ws_manager.send_to_user(user_id=participant.user_id, payload=payload)


async def _broadcast_live_location_stopped(
    *,
    request: Request | WebSocket,
    messenger: MessengerServiceDep,
    share,
    reason: str,
) -> None:
    ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
    participants = messenger.get_chat_participants(chat_id=share.chat_id)
    payload = {
        'type': 'live_location_stopped',
        'chat_id': share.chat_id,
        'user_id': share.user_id,
        'username': share.username,
        'reason': reason,
    }
    for participant in participants:
        await ws_manager.send_to_user(user_id=participant.user_id, payload=payload)


async def _emit_live_location_stopped_message(
    *,
    request: Request | WebSocket,
    messenger: MessengerServiceDep,
    share,
) -> None:
    ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
    connected_user_ids = ws_manager.get_connected_user_ids_for_chat(
        share.chat_id)
    sent_message = messenger.send_message(
        chat_id=share.chat_id,
        sender_id=share.user_id,
        connected_user_ids=connected_user_ids,
        content='Пользователь перестал делиться местоположением',
    )
    participants = messenger.get_chat_participants(chat_id=share.chat_id)
    for participant in participants:
        serialized_message = _serialize_message(
            sent_message, participant.id).model_dump()
        await ws_manager.send_to_user(
            user_id=participant.user_id,
            payload={
                'type': 'message',
                'message': serialized_message,
            },
        )


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
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return _serialize_watch_room(room, youtube_access_mode=access_context.youtube_access_mode)


@router.get('/watch-rooms')
async def get_watch_room_id(
    user: AuthUserDep,
    chat_id: int,
    message_id: int,
):
    # room_id = id_by_pair(chat_id, message_id)
    ...


@router.get('/watch-rooms/by-chat/{chat_id}')
async def get_watch_room_by_chat(
    chat_id: int,
    youtube_video_id: str,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
) -> WatchRoomResponse:
    messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    room = watch_rooms.find_room(
        chat_id=chat_id, youtube_video_id=youtube_video_id)
    if room is None:
        raise HTTPException(status_code=404, detail='Room not found')
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return _serialize_watch_room(room, youtube_access_mode=access_context.youtube_access_mode)


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
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return _serialize_watch_room(room, youtube_access_mode=access_context.youtube_access_mode)


@router.get('/watch-rooms/{room_id}/messages')
async def get_watch_room_messages(
    room_id: str,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    watch_rooms: WatchRoomServiceDep,
    limit: int = Query(default=100, ge=1, le=300),
) -> list[WatchRoomChatMessageResponse]:
    room = watch_rooms.get_room(room_id)
    if not _can_access_watch_room(room, user.id, messenger):
        raise HTTPException(status_code=403, detail='Access denied')
    return [
        _serialize_watch_room_chat_message(message)
        for message in watch_rooms.list_chat_messages(room_id=room_id, limit=limit)
    ]


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
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return _serialize_watch_room(room, youtube_access_mode=access_context.youtube_access_mode)


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
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return _serialize_watch_room(room, youtube_access_mode=access_context.youtube_access_mode)


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
        user_id=user.id,
        current_time_seconds=payload.current_time_seconds,
        is_playing=payload.is_playing,
    )
    await _broadcast_watch_room_update(request=request, messenger=messenger, room=room)
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return _serialize_watch_room(room, youtube_access_mode=access_context.youtube_access_mode)


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
        messenger.get_chat_participant(
            chat_id=payload.target_chat_id, user_id=user.id)
        try:
            messenger.get_chat_participant(
                chat_id=payload.target_chat_id, user_id=payload.target_user_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail='Target user is not in target chat') from exc

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
    access_context = resolve_youtube_access_context_for_user(
        username=user.username,
        persisted_tier=user.subscription_tier,
        persisted_youtube_assisted_enabled=user.youtube_assisted_enabled,
    )
    return _serialize_watch_room(room, youtube_access_mode=access_context.youtube_access_mode)


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
        ChatGroupResponse(
            id=group.id,
            title=group.title,
            chat_ids=group.chat_ids,
            unread_messages_count=group.unread_messages_count,
        )
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
    participant, messages = messenger.get_chat_messages(
        chat_id=chat_id, user_id=user.id)
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
        raise HTTPException(
            status_code=403, detail='Attachment does not belong to chat')

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
        record = storage.complete_attachment_upload(
            attachment_id,
            duration_ms=payload.duration_ms,
            duration_seconds=payload.duration_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if f'chat-attachments/{chat_id}/' not in record.storage_key:
        raise HTTPException(
            status_code=403, detail='Attachment does not belong to chat')

    return AttachmentCompleteResponse(
        attachment_id=record.attachment_id,
        status=record.status,  # type: ignore[arg-type]
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        duration_ms=record.duration_ms,
        duration_seconds=record.duration_seconds,
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
        raise HTTPException(
            status_code=403, detail='Attachment does not belong to chat')

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
            raise HTTPException(
                status_code=403, detail='Attachment does not belong to chat')
        if record.local_path is not None:
            return FileResponse(
                path=record.local_path,
                media_type=record.mime_type or 'application/octet-stream',
                filename=record.original_name,
            )

        presigned_url = storage.generate_attachment_download_url(
            storage_key=record.storage_key)
        return RedirectResponse(url=presigned_url, status_code=307)

    if key is None:
        raise HTTPException(status_code=404, detail='Attachment not found')
    resolved_key = unquote(key)
    if not resolved_key.startswith(f'chat-attachments/{chat_id}/'):
        raise HTTPException(
            status_code=403, detail='Attachment does not belong to chat')

    presigned_url = storage.generate_attachment_download_url(
        storage_key=resolved_key)
    return RedirectResponse(url=presigned_url, status_code=307)


@router.post('/chats/{chat_id}/messages')
async def send_chat_message(
    request: Request,
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    storage: StorageServiceDep,
    payload: SendMessageRequest = Body(),
) -> ChatMessageResponse:
    participant = messenger.get_chat_participant(
        chat_id=chat_id, user_id=user.id)
    content = payload.content
    if payload.attachment_id is not None:
        record = storage.get_attachment_record(payload.attachment_id)
        if record is None:
            raise HTTPException(status_code=400, detail='Attachment not found')
        if record.status != 'ready':
            raise HTTPException(
                status_code=400, detail='Attachment is not ready')
        if f'chat-attachments/{chat_id}/' not in record.storage_key:
            raise HTTPException(
                status_code=403, detail='Attachment does not belong to chat')

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
            duration_ms=record.duration_ms,
            duration_seconds=record.duration_seconds,
        )

    try:
        ws_manager: WebSocketConnectionManager = request.app.state.ws_manager
        connected_user_ids = ws_manager.get_connected_user_ids_for_chat(
            chat_id)
        message = messenger.send_message(
            chat_id,
            user.id,
            content,
            reference_message_id=payload.reference_message_id,
            forwarded_from_message_id=payload.forwarded_from_message_id,
            connected_user_ids=connected_user_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_message(message, participant.id)


@router.delete('/chats/{chat_id}/messages/{message_id}')
async def delete_chat_message(
    chat_id: int,
    message_id: int,
    request: Request,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
) -> ChatMessageDeleteResponse:
    try:
        deleted_message = messenger.delete_message(
            chat_id=chat_id,
            user_id=user.id,
            message_id=message_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _broadcast_message_deleted(
        request=request,
        messenger=messenger,
        chat_id=chat_id,
        message_id=deleted_message.id,
    )
    return _serialize_message_deleted(chat_id=chat_id, message_id=deleted_message.id)


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
    watch_rooms: WatchRoomServiceDep,
    live_locations: LiveLocationServiceDep,
):
    access_token = websocket.cookies.get(
        'access_token') or websocket.query_params.get('access_token')
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
                expired_shares = live_locations.pop_expired_shares(
                    chat_id=request.chat_id,
                    now=time.time(),
                )
                for expired_share in expired_shares:
                    await _broadcast_live_location_stopped(
                        request=websocket,
                        messenger=messenger,
                        share=expired_share,
                        reason='expired',
                    )
                    await _emit_live_location_stopped_message(
                        request=websocket,
                        messenger=messenger,
                        share=expired_share,
                    )

                if request.action == 'get_messages':
                    ws_manager.set_active_chat(
                        user_id=user.id,
                        websocket=websocket,
                        chat_id=request.chat_id,
                    )
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
                                _serialize_message(
                                    message, participant.id).model_dump()
                                for message in messages
                            ],
                        }
                    )
                    continue

                if request.action == 'watch_room_playback':
                    room = watch_rooms.get_room(request.room_id or '')
                    if not _can_access_watch_room(room, user.id, messenger):
                        raise ValueError('Access denied')
                    room = watch_rooms.sync_room(
                        room_id=room.id,
                        user_id=user.id,
                        current_time_seconds=request.current_time_seconds or 0.0,
                        is_playing=bool(request.is_playing),
                    )
                    await _broadcast_watch_room_update(
                        request=websocket,
                        messenger=messenger,
                        room=room,
                    )
                    continue

                if request.action == 'watch_room_chat_send':
                    room = watch_rooms.get_room(request.room_id or '')
                    if not _can_access_watch_room(room, user.id, messenger):
                        raise ValueError('Access denied')
                    chat_message = watch_rooms.add_chat_message(
                        room_id=room.id,
                        user_id=user.id,
                        username=user.username,
                        content=request.content or '',
                    )
                    await _broadcast_watch_room_chat_message(
                        request=websocket,
                        messenger=messenger,
                        room=room,
                        message=chat_message,
                    )
                    continue

                if request.action == 'live_location_start':
                    messenger.get_chat_participant(
                        chat_id=request.chat_id, user_id=user.id)
                    share = live_locations.upsert_share(
                        chat_id=request.chat_id,
                        user_id=user.id,
                        username=user.username,
                        avatar_url=user.avatar_url,
                        latitude=float(request.latitude or 0.0),
                        longitude=float(request.longitude or 0.0),
                        accuracy_meters=request.accuracy_meters,
                        expires_at=request.expires_at_timestamp,
                    )
                    await _broadcast_live_location_update(
                        request=websocket,
                        messenger=messenger,
                        share=share,
                    )
                    continue

                if request.action == 'live_location_update':
                    messenger.get_chat_participant(
                        chat_id=request.chat_id, user_id=user.id)
                    share = live_locations.update_share(
                        chat_id=request.chat_id,
                        user_id=user.id,
                        latitude=float(request.latitude or 0.0),
                        longitude=float(request.longitude or 0.0),
                        accuracy_meters=request.accuracy_meters,
                    )
                    await _broadcast_live_location_update(
                        request=websocket,
                        messenger=messenger,
                        share=share,
                    )
                    continue

                if request.action == 'live_location_stop':
                    messenger.get_chat_participant(
                        chat_id=request.chat_id, user_id=user.id)
                    stopped_share = live_locations.stop_share(
                        chat_id=request.chat_id, user_id=user.id)
                    if stopped_share is not None:
                        await _broadcast_live_location_stopped(
                            request=websocket,
                            messenger=messenger,
                            share=stopped_share,
                            reason='stopped',
                        )
                        await _emit_live_location_stopped_message(
                            request=websocket,
                            messenger=messenger,
                            share=stopped_share,
                        )
                    continue

                connected_user_ids = ws_manager.get_connected_user_ids_for_chat(
                    request.chat_id)
                sent_message = messenger.send_message(
                    chat_id=request.chat_id,
                    sender_id=user.id,
                    content=request.content or '',
                    reference_message_id=request.reference_message_id,
                    forwarded_from_message_id=request.forwarded_from_message_id,
                    connected_user_ids=connected_user_ids,
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

                participants = messenger.get_chat_participants(
                    chat_id=request.chat_id)
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
        if not ws_manager.has_user_connections(user.id):
            stopped_shares = live_locations.stop_all_for_user(user_id=user.id)
            for stopped_share in stopped_shares:
                await _broadcast_live_location_stopped(
                    request=websocket,
                    messenger=messenger,
                    share=stopped_share,
                    reason='disconnected',
                )
                await _emit_live_location_stopped_message(
                    request=websocket,
                    messenger=messenger,
                    share=stopped_share,
                )
            changed_rooms = watch_rooms.leave_user_from_all_rooms(user.id)
            for room in changed_rooms:
                await _broadcast_watch_room_update(
                    request=websocket,
                    messenger=messenger,
                    room=room,
                )
