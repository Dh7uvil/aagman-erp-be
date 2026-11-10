"""FastAPI dependencies for dashboard."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory.dashboard.service import DashboardService


async def get_dashboard_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardService:
    return DashboardService(session)


DashboardServiceDependency = Annotated[DashboardService, Depends(get_dashboard_service)]
