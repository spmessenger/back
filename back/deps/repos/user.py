from typing import Annotated, TypeAlias
from fastapi import Depends
from core.repos.user import AbstractUserRepo, DbUserRepo

UserRepoDep: TypeAlias = Annotated[AbstractUserRepo, Depends(DbUserRepo)]
