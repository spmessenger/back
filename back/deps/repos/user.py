from typing import Annotated
from fastapi import Depends
from core.repos.user import AbstractUserRepo, DbUserRepo

UserRepoDep = Annotated[AbstractUserRepo, Depends(DbUserRepo)]
