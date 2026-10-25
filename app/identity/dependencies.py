"""Slice-level FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.identity.audit_service import AuditLogService
from app.identity.org_service import OrganizationService
from app.identity.service import AuthService
from app.identity.company_service import CompanyService
from app.identity.warehouse_service import WarehouseService


def get_auth_service(session: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    return AuthService(session)


def get_organization_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationService:
    return OrganizationService(session)


def get_warehouse_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WarehouseService:
    return WarehouseService(session)


def get_company_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CompanyService:
    return CompanyService(session)


def get_audit_log_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuditLogService:
    return AuditLogService(session)


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
OrganizationServiceDependency = Annotated[OrganizationService, Depends(get_organization_service)]
WarehouseServiceDependency = Annotated[WarehouseService, Depends(get_warehouse_service)]
CompanyServiceDependency = Annotated[CompanyService, Depends(get_company_service)]
AuditLogServiceDependency = Annotated[AuditLogService, Depends(get_audit_log_service)]
