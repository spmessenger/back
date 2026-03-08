from typing import Annotated, TypeAlias
from fastapi import Depends
from core.repos.participant import AbstractParticipantRepo, DbParticipantRepo

ParticipantRepoDep: TypeAlias = Annotated[AbstractParticipantRepo, Depends(DbParticipantRepo)]
