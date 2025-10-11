from typing import Annotated
from fastapi import APIRouter, Body
from back.deps.services.auth import AuthServiceDep

router = APIRouter()


@router.post('/login')
def login(
    username: Annotated[str, Body(embed=False)],
    password: Annotated[str, Body(embed=False)],
    service: AuthServiceDep
):
    _, auth = service.login(username, password)
    return {'auth': auth}


@router.post('/register')
async def register(
    username: Annotated[str, Body(embed=False)],
    password: Annotated[str, Body(embed=False)],
    service: AuthServiceDep
):
    _, private_chat, auth = service.register(username, password)
    return {'auth': auth, 'chats': [private_chat]}
