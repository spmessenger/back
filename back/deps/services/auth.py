from typing import Annotated
from fastapi import Depends
from core.services.auth import AuthService
from ..repos import UserRepoDep
from ..services.messenger import MessengerServiceDep


def get_auth_service(user_repo: UserRepoDep, messenger: MessengerServiceDep) -> AuthService:
    return AuthService(user_repo, messenger)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
