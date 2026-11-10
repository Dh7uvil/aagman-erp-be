"""FastAPI dependencies for solvents."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory.solvents.service import SolventService


async def get_solvent_service(session: Annotated[AsyncSession, Depends(get_db)]) -> SolventService:
    return SolventService(session)


SolventServiceDependency = Annotated[SolventService, Depends(get_solvent_service)]
