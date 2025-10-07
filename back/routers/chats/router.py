from fastapi import APIRouter
from core.entities.chat import Chat
from back.deps.auth import AuthUserDep

router = APIRouter()


@router.get('/chats')
async def get_chats(
    user: AuthUserDep,
) -> list[Chat]:
    return {'chats': [{'id': 1, 'type': 'private'}]}
