from fastapi import APIRouter
from core.entities.chat import Chat
from back.deps.auth import AuthUserDep
from back.deps.repos.chat import ChatRepoDep

router = APIRouter()


@router.get('/chats')
async def get_chats(
    user: AuthUserDep,
    chat_repo: ChatRepoDep,
) -> list[Chat]:
    return chat_repo.find_all(user_id=user.id)
