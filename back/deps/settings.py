from typing import Annotated
from fastapi import Depends
from core.settings import settings as core_settings


SecretKeyDep = Annotated[str, Depends(lambda: core_settings.SECRET_KEY)]
