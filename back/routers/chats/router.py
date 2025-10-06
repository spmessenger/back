from fastapi import APIRouter


router = APIRouter()


@router.get('/chats')
async def get_chats():
    return {'chats': [{'id': 1, 'type': 'private'}]}
