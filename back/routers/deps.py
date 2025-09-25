from typing import Annotated
from fastapi import Depends
from core.services.auth import AuthService
from core.repos.user import InMemoryUserRepo
from core.repos.chat import InMemoryChatRepo
from core.repos.participant import InMemoryParticipantRepo

AuthServiceDep = Annotated[AuthService, Depends(lambda: AuthService(
    InMemoryUserRepo(), InMemoryChatRepo(), InMemoryParticipantRepo()))]
