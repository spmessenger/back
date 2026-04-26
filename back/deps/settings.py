from typing import Annotated, TypeAlias
from fastapi import Depends
from core.settings import get_settings

core_settings = get_settings()


SecretKeyDep: TypeAlias = Annotated[str,
                                    Depends(lambda: core_settings.SECRET_KEY)]
