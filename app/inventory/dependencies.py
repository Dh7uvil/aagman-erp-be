"""FastAPI dependencies for inventory."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.inventory.service import InventoryService


async def get_inventory_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InventoryService:
    return InventoryService(session)


InventoryServiceDependency = Annotated[InventoryService, Depends(get_inventory_service)]
