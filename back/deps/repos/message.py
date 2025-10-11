from typing import Annotated
from fastapi import Depends
from core.repos.message import AbstractMessageRepo, DbMessageRepo

MessageRepoDep = Annotated[AbstractMessageRepo, Depends(DbMessageRepo)]
