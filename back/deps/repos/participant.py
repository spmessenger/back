from typing import Annotated
from fastapi import Depends
from core.repos.participant import AbstractParticipantRepo, DbParticipantRepo

ParticipantRepoDep = Annotated[AbstractParticipantRepo, Depends(DbParticipantRepo)]
