from typing import Annotated
from fastapi import Depends
from core.repos.user import AbstractUserRepo, InMemoryUserRepo
from ..settings import RepoImplTypeDep

InMemoryUserRepoDep = Annotated[InMemoryUserRepo, Depends(InMemoryUserRepo)]


def get_user_repo(
    repo_type: RepoImplTypeDep,
    memory_user_repo: InMemoryUserRepoDep,
) -> AbstractUserRepo:
    match repo_type:
        case RepoImplTypeDep.MEMORY:
            return memory_user_repo
        case RepoImplTypeDep.DB:
            raise NotImplementedError()


UserRepoDep = Annotated[AbstractUserRepo, Depends(InMemoryUserRepo)]
