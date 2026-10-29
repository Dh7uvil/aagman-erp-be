"""FastAPI dependencies for jobs."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory.jobs.returns_service import CylinderReturnService
from app.inventory.jobs.service import JobService


async def get_job_service(session: Annotated[AsyncSession, Depends(get_db)]) -> JobService:
    return JobService(session)


async def get_cylinder_return_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CylinderReturnService:
    return CylinderReturnService(session)


JobServiceDependency = Annotated[JobService, Depends(get_job_service)]
CylinderReturnServiceDependency = Annotated[CylinderReturnService, Depends(get_cylinder_return_service)]
