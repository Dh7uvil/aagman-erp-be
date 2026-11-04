"""FastAPI dependencies for inks."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory.inks.service import InkService


async def get_ink_service(session: Annotated[AsyncSession, Depends(get_db)]) -> InkService:
    return InkService(session)


InkServiceDependency = Annotated[InkService, Depends(get_ink_service)]
