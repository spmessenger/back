from __future__ import annotations
from fastapi import APIRouter, Body
from core.entities.chat import Chat
from back.deps.auth import AuthUserDep
from back.deps.repos.chat import ChatRepoDep
from back.deps.repos.message import MessageRepoDep
from back.deps.repos.participant import ParticipantRepoDep
from back.deps.repos.user import UserRepoDep
from back.deps.services.messenger import MessengerServiceDep
from back.deps.services.storage import StorageServiceDep
from .schemas import (
    AvailableUser,
    ChatCreation,
    ChatMessageResponse,
    GroupCreationRequest,
    SendMessageRequest,
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
    participant_repo: ParticipantRepoDep,
    message_repo: MessageRepoDep,
) -> list[ChatMessageResponse]:
    participant = participant_repo.get_one(chat_id=chat_id, user_id=user.id)
    messages = message_repo.find_all(chat_id=chat_id)
    return [_serialize_message(message, participant.id) for message in messages]


@router.post('/chats/{chat_id}/messages')
async def send_chat_message(
    chat_id: int,
    user: AuthUserDep,
    messenger: MessengerServiceDep,
    participant_repo: ParticipantRepoDep,
    payload: SendMessageRequest = Body(),
) -> ChatMessageResponse:
    participant = participant_repo.get_one(chat_id=chat_id, user_id=user.id)
    message = messenger.send_message(chat_id, user.id, payload.content)
    return _serialize_message(message, participant.id)
