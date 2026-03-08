from typing import Annotated, TypeAlias
from fastapi import Depends
from core.repos.chat import AbstractChatRepo, DbChatRepo

ChatRepoDep: TypeAlias = Annotated[AbstractChatRepo, Depends(DbChatRepo)]
