"""FastAPI dependencies for adhesives."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory.adhesives.service import AdhesiveService


async def get_adhesive_service(session: Annotated[AsyncSession, Depends(get_db)]) -> AdhesiveService:
    return AdhesiveService(session)


AdhesiveServiceDependency = Annotated[AdhesiveService, Depends(get_adhesive_service)]
