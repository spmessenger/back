from fastapi import APIRouter, Body
from core.entities.chat import Chat
from back.deps.auth import AuthUserDep
from back.deps.repos.chat import ChatRepoDep
from back.deps.services.messenger import MessengerServiceDep
from .schemas import ChatCreation

router = APIRouter(tags=['Chats'])


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
    title: str = Body(),
    participants: list[int] = Body(),
) -> ChatCreation:
    chat, participants = messenger.create_group_chat(user.id, title, participants)
    return ChatCreation(chat=chat, participants=participants)
