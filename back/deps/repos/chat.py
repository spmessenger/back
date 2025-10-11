from typing import Annotated
from fastapi import Depends
from core.repos.chat import AbstractChatRepo, DbChatRepo

ChatRepoDep = Annotated[AbstractChatRepo, Depends(DbChatRepo)]