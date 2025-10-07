from typing import Annotated
from fastapi import Depends
from core.settings import settings as core_settings
from back.settings import settings, RepoImplType


SecretKeyDep = Annotated[str, Depends(lambda: core_settings.SECRET_KEY)]
RepoImplTypeDep = Annotated[RepoImplType, Depends(lambda: settings.REPO_IMPL_TYPE)]
