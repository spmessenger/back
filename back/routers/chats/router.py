from __future__ import annotations
from fastapi import APIRouter, Body, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from core.entities.chat import Chat
from back.deps.auth import AuthUserDep, get_current_user_by_token
from back.deps.settings import SecretKeyDep
from back.deps.repos.chat import ChatRepoDep
from back.deps.repos.user import UserRepoDep
from back.deps.services.messenger import MessengerServiceDep
from back.services.ws_manager import WebSocketConnectionManager
from back.deps.services.storage import StorageServiceDep
from .schemas import (
    AvailableUser,
    ChatCreation,
    ChatMessageResponse,
    GroupCreationRequest,
    SendMessageRequest,
    WsChatActionRequest,
)

router = APIRouter(tags=['Chats'])


def _serialize_message(message, own_participant_id: int) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        chat_id=message.chat_id,
        content=message.content,
        created_at_timestamp=float(message.created_at_timestamp),
        is_own=message.participant_id == own_participant_id,
    )


@router.get('/available-users')
async def get_available_users(
    user: AuthUserDep,
    user_repo: UserRepoDep,
) -> list[AvailableUser]:
    users = user_repo.find_all()
    return [
        AvailableUser(id=registered_user.id, username=registered_user.username)
        for registered_user in users
        if registered_user.id != user.id
    ]


@router.get('/chats')
async def get_chats(
    user: AuthUserDep,
    chat_repo: ChatRepoDep,
) -> list[Chat]:
    return chat_repo.find_all(user_id=user.id)


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
    return ChatCreation(chat=chat, participants=participants)


@router.get('/chats/{chat_id}/messages')
async def get_chat_messages(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
) -> list[ChatMessageResponse]:
    participant, messages = messenger.get_chat_messages(chat_id=chat_id, user_id=user.id)
    return [_serialize_message(message, participant.id) for message in messages]


@router.post('/chats/{chat_id}/messages')
async def send_chat_message(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    payload: SendMessageRequest = Body(),
) -> ChatMessageResponse:
    participant = messenger.get_chat_participant(chat_id=chat_id, user_id=user.id)
    message = messenger.send_message(chat_id, user.id, payload.content)
    return _serialize_message(message, participant.id)


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
                    participant, messages = messenger.get_chat_messages(
                        chat_id=request.chat_id,
                        user_id=user.id,
                    )
                    await websocket.send_json(
                        {
                            'type': 'messages',
                            'chat_id': request.chat_id,
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
                )
                sender_participant = messenger.get_chat_participant(
                    chat_id=request.chat_id,
                    user_id=user.id,
                )
                participants = messenger.get_chat_participants(chat_id=request.chat_id)
                sender_notified = False
                for participant in participants:
                    serialized_message = _serialize_message(
                        sent_message,
                        participant.id,
                    ).model_dump()
                    if participant.user_id == user.id:
                        serialized_message['client_message_id'] = request.client_message_id
                        sender_notified = True

                    await ws_manager.send_to_user(
                        user_id=participant.user_id,
                        payload={
                            'type': 'message',
                            'message': serialized_message,
                        },
                    )

                if not sender_notified:
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
