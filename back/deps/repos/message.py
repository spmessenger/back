from typing import Annotated, TypeAlias
from fastapi import Depends
from core.repos.message import AbstractMessageRepo, DbMessageRepo

MessageRepoDep: TypeAlias = Annotated[AbstractMessageRepo, Depends(DbMessageRepo)]
