from typing import Annotated, TypeAlias
from fastapi import Depends
from core.settings import settings as core_settings


SecretKeyDep: TypeAlias = Annotated[str, Depends(lambda: core_settings.SECRET_KEY)]
