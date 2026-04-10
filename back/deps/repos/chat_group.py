from typing import Annotated, TypeAlias
from fastapi import Depends
from core.repos.chat_group import AbstractChatGroupRepo, DbChatGroupRepo

ChatGroupRepoDep: TypeAlias = Annotated[AbstractChatGroupRepo, Depends(DbChatGroupRepo)]
