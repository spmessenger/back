from fastapi import APIRouter
from back.deps.auth import AuthUserDep
from back.deps.services.rooms import YouTubeRoomDep



router = APIRouter(tags=['Rooms'], prefix='/rooms')


@router.post('/youtube')
def create_youtube_room(
    user: AuthUserDep,
    chat_id: int,
    message_id: int,
    service: YouTubeRoomDep,
):
    ...
