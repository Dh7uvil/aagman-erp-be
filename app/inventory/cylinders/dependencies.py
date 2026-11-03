"""FastAPI dependencies for jobs."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory.cylinders.returns_service import CylinderReturnService
from app.inventory.cylinders.service import CylinderService


async def get_cylinder_service(session: Annotated[AsyncSession, Depends(get_db)]) -> CylinderService:
    return CylinderService(session)


async def get_cylinder_return_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CylinderReturnService:
    return CylinderReturnService(session)


CylinderServiceDependency = Annotated[CylinderService, Depends(get_cylinder_service)]
CylinderReturnServiceDependency = Annotated[CylinderReturnService, Depends(get_cylinder_return_service)]
