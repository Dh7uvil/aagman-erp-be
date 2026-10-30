"""Organization settings: singleton org, branches, and departments."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.files import MIME_JPEG, MIME_PNG, MIME_WEBP, validate_upload
from app.common.utils.time import utcnow
from app.core.config import get_settings
from app.core.enums import AddressType, AuditAction, BranchStatus, IDENTITY_MODULE
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.identity import local_storage
from app.integrations.storage import S3Storage, build_org_logo_key, get_optional_storage
from app.identity.models import Address, Branch, Department, Organization, User
from app.identity.org_repository import OrganizationRepository
from app.identity.repository import AccessRepository
from app.identity.schemas import (
    AddressPayload,
    AddressResponse,
    BranchCreate,
    BranchResponse,
    BranchSummary,
    BranchUpdate,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    OrganizationBrandingResponse,
    OrganizationResponse,
    OrganizationSettings,
    OrganizationUpdate,
    UserSummary,
    format_address_label,
)

LOGO_MAX_SIZE_MB = 2
LOGO_ALLOWED_MIME_TYPES = (MIME_JPEG, MIME_PNG, MIME_WEBP)


def _address_values(payload: AddressPayload) -> dict[str, object]:
    return payload.model_dump(exclude_none=False, exclude={"address_line_3"})


def _address_has_values(payload: AddressPayload) -> bool:
    return any(value is not None for value in _address_values(payload).values())


def _address_response(address: Address | None) -> AddressResponse | None:
    if address is None:
        return None
    return AddressResponse.model_validate(address)


def _unique_logo_filename(filename: str) -> str:
    """Keep replacements from colliding on the same object key."""

    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    return f"{uuid4().hex}.{ext}" if ext else uuid4().hex


def _logo_url(logo_storage_key: str | None) -> str | None:
    if not logo_storage_key:
        return None
    settings = get_settings()
    path = f"{settings.api_v1_prefix}/organization/logo"
    version = quote(logo_storage_key.rsplit("/", 1)[-1], safe=".-_")
    return f"{path}?v={version}"


class OrganizationService:
    """Singleton organization, branch, and department use cases."""

    def __init__(self, session: AsyncSession, storage: S3Storage | None = None) -> None:
        self.session = session
        self.storage = storage if storage is not None else get_optional_storage()
        self.access = AccessRepository(session)
        self.org = OrganizationRepository(session)
        self.audit = AuditWriter(session)

    async def get_organization(self) -> OrganizationResponse:
        org = await self._require_organization()
        return await self._organization_response(org)

    async def get_organization_branding(self) -> OrganizationBrandingResponse:
        org = await self._require_organization()
        return OrganizationBrandingResponse(
            name=org.name,
            logo_url=_logo_url(org.logo_storage_key),
        )

    async def get_logo(self) -> tuple[bytes, str]:
        org = await self._require_organization()
        if org.logo_storage_key is None:
            raise ResourceNotFoundError("Organization logo not found")
        if self.storage is not None:
            return await self.storage.download(key=org.logo_storage_key)
        return local_storage.read_logo(org.logo_storage_key)

    async def update_organization(
        self,
        payload: OrganizationUpdate,
        *,
        actor_user_id: UUID,
    ) -> OrganizationResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            org = await self._require_organization(for_update=True)
            old_values = self._organization_snapshot(org)
            headquarters = values.pop("headquarters", None)
            settings_payload = values.pop("settings", None)
            if "name" in values and values["name"] is not None:
                org.name = values["name"]
            if "timezone" in values and values["timezone"] is not None:
                org.timezone = values["timezone"]
            for field in ("industry", "website", "contact_email", "phone"):
                if field in values:
                    setattr(org, field, values[field])
            if "fiscal_year_start_month" in values and values["fiscal_year_start_month"] is not None:
                org.fiscal_year_start_month = int(values["fiscal_year_start_month"])
            if "fiscal_year_start_day" in values and values["fiscal_year_start_day"] is not None:
                org.fiscal_year_start_day = int(values["fiscal_year_start_day"])
            if headquarters is not None:
                org.headquarters_address_id = await self._upsert_address(
                    org.headquarters_address_id,
                    headquarters,
                    address_type=AddressType.HEADQUARTERS,
                )
            if settings_payload is not None:
                current = OrganizationSettings.model_validate(org.settings or {})
                merged = OrganizationSettings.model_validate(
                    {**current.model_dump(), **settings_payload.model_dump(exclude_unset=True)}
                )
                org.settings = merged.model_dump(mode="json")
            await self.session.flush()
            await self.session.refresh(org)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="organization",
                entity_id=org.id,
                old_values=old_values,
                new_values=self._organization_snapshot(org),
            )
            return await self._organization_response(org)

    async def upload_logo(
        self,
        *,
        filename: str | None,
        content: bytes,
        actor_user_id: UUID,
    ) -> OrganizationResponse:
        validated = validate_upload(
            content,
            filename=filename,
            max_upload_size_mb=LOGO_MAX_SIZE_MB,
            allowed_mime_types=LOGO_ALLOWED_MIME_TYPES,
        )
        async with transaction(self.session):
            org = await self._require_organization(for_update=True)
            stored_name = _unique_logo_filename(validated.filename)
            if self.storage is not None:
                new_key = build_org_logo_key(
                    organization_id=org.id,
                    filename=stored_name,
                )
            else:
                new_key = local_storage.logo_relative_key(stored_name)
            old_key = org.logo_storage_key
            old_values = self._organization_snapshot(org)
            org.logo_storage_key = new_key
            org.updated_at = utcnow()
            await self.session.flush()
            await self.session.refresh(org)
            if self.storage is not None:
                await self.storage.upload(
                    key=new_key,
                    body=validated.content,
                    content_type=validated.content_type,
                )
                if old_key and old_key != new_key:
                    await self.storage.delete(key=old_key)
            else:
                local_storage.write_logo(new_key, validated.content)
                if old_key and old_key != new_key:
                    local_storage.delete_logo(old_key)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="organization",
                entity_id=org.id,
                old_values=old_values,
                new_values=self._organization_snapshot(org),
            )
            await self.session.refresh(org)
            return await self._organization_response(org)

    async def delete_logo(self, *, actor_user_id: UUID) -> OrganizationResponse:
        async with transaction(self.session):
            org = await self._require_organization(for_update=True)
            old_key = org.logo_storage_key
            if not old_key:
                raise ResourceNotFoundError("Organization logo not found")
            old_values = self._organization_snapshot(org)
            org.logo_storage_key = None
            org.updated_at = utcnow()
            await self.session.flush()
            await self.session.refresh(org)
            if self.storage is not None:
                await self.storage.delete(key=old_key)
            else:
                local_storage.delete_logo(old_key)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="organization",
                entity_id=org.id,
                old_values=old_values,
                new_values=self._organization_snapshot(org),
            )
            await self.session.refresh(org)
            return await self._organization_response(org)

    async def list_branches(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
    ) -> tuple[list[BranchResponse], int]:
        filters = {"status": status} if status is not None else None
        branches, total = await self.org.list_branches(
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        return await self._branch_responses(list(branches)), total

    async def create_branch(
        self,
        payload: BranchCreate,
        *,
        actor_user_id: UUID,
    ) -> BranchResponse:
        async with transaction(self.session):
            try:
                address_id = await self._upsert_address(None, payload.address)
                branch = await self.org.create_branch(
                    {
                        "name": payload.name,
                        "code": payload.code,
                        "status": payload.status.value,
                        "phone": payload.phone,
                        "timezone": payload.timezone,
                        "address_id": address_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A branch with this code already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="branch",
                entity_id=branch.id,
                new_values=await self._branch_snapshot(branch),
            )
            await self.session.refresh(branch)
            return (await self._branch_responses([branch]))[0]

    async def get_branch(self, branch_id: UUID) -> BranchResponse:
        branch = await self._require_branch(branch_id)
        return (await self._branch_responses([branch]))[0]

    async def update_branch(
        self,
        branch_id: UUID,
        payload: BranchUpdate,
        *,
        actor_user_id: UUID,
    ) -> BranchResponse:
        values = payload.model_dump(exclude_unset=True)
        address_payload = values.pop("address", None)
        if "status" in values and values["status"] is not None:
            values["status"] = str(values["status"])
        async with transaction(self.session):
            branch = await self._require_branch(branch_id)
            old_values = await self._branch_snapshot(branch)
            if address_payload is not None:
                values["address_id"] = await self._upsert_address(
                    branch.address_id,
                    AddressPayload.model_validate(address_payload),
                )
            for name, value in values.items():
                setattr(branch, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A branch with this code already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="branch",
                entity_id=branch.id,
                old_values=old_values,
                new_values=await self._branch_snapshot(branch),
            )
            await self.session.refresh(branch)
            return (await self._branch_responses([branch]))[0]

    async def delete_branch(self, branch_id: UUID, *, actor_user_id: UUID) -> BranchResponse:
        async with transaction(self.session):
            branch = await self._require_branch(branch_id)
            if await self.org.count_departments_for_branch(branch_id) > 0:
                raise ValidationError("Cannot delete a branch that still has departments")
            if await self.org.count_users_for_branch(branch_id) > 0:
                raise ValidationError("Cannot delete a branch that still has users")
            response = (await self._branch_responses([branch]))[0]
            await self.org.soft_delete_branch(branch_id)
            if branch.address_id is not None:
                await self.org.addresses.soft_delete(branch.address_id)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="branch",
                entity_id=branch.id,
                old_values=await self._branch_snapshot(branch),
            )
            return response

    async def list_departments(
        self,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        branch_id: UUID | None = None,
    ) -> tuple[list[DepartmentResponse], int]:
        filters: dict[str, object] | None = {"branch_id": branch_id} if branch_id else None
        departments, total = await self.org.list_departments(
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        return await self._department_responses(list(departments)), total

    async def create_department(
        self,
        payload: DepartmentCreate,
        *,
        actor_user_id: UUID,
    ) -> DepartmentResponse:
        async with transaction(self.session):
            await self._require_branch(payload.branch_id)
            await self._require_manager(payload.manager_id)
            try:
                department = await self.org.create_department(
                    {
                        "name": payload.name,
                        "code": payload.code,
                        "branch_id": payload.branch_id,
                        "manager_id": payload.manager_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A department with this code already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="department",
                entity_id=department.id,
                new_values=await self._department_snapshot(department),
            )
            await self.session.refresh(department)
            return (await self._department_responses([department]))[0]

    async def get_department(self, department_id: UUID) -> DepartmentResponse:
        department = await self._require_department(department_id)
        return (await self._department_responses([department]))[0]

    async def update_department(
        self,
        department_id: UUID,
        payload: DepartmentUpdate,
        *,
        actor_user_id: UUID,
    ) -> DepartmentResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            department = await self._require_department(department_id)
            old_values = await self._department_snapshot(department)
            if "branch_id" in values and values["branch_id"] is not None:
                await self._require_branch(values["branch_id"])
            if "manager_id" in values:
                await self._require_manager(values["manager_id"])
            for name, value in values.items():
                setattr(department, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A department with this code already exists") from exc
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="department",
                entity_id=department.id,
                old_values=old_values,
                new_values=await self._department_snapshot(department),
            )
            await self.session.refresh(department)
            return (await self._department_responses([department]))[0]

    async def delete_department(self, department_id: UUID, *, actor_user_id: UUID) -> DepartmentResponse:
        async with transaction(self.session):
            department = await self._require_department(department_id)
            if await self.org.count_users_for_department(department_id) > 0:
                raise ValidationError("Cannot delete a department that still has users")
            response = (await self._department_responses([department]))[0]
            await self.org.soft_delete_department(department_id)
            await self.audit.write(
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="department",
                entity_id=department.id,
                old_values=await self._department_snapshot(department),
            )
            return response

    async def upsert_address(
        self,
        address_id: UUID | None,
        payload: AddressPayload | None,
        *,
        address_type: AddressType,
    ) -> UUID | None:
        return await self._upsert_address(address_id, payload, address_type=address_type)

    async def _require_organization(self, *, for_update: bool = False) -> Organization:
        org = await self.access.get_organization(for_update=for_update)
        if org is None:
            raise ResourceNotFoundError("Organization not found")
        return org

    async def _require_branch(self, branch_id: UUID) -> Branch:
        branch = await self.org.get_branch(branch_id)
        if branch is None:
            raise ResourceNotFoundError("Branch not found")
        return branch

    async def _require_department(self, department_id: UUID) -> Department:
        department = await self.org.get_department(department_id)
        if department is None:
            raise ResourceNotFoundError("Department not found")
        return department

    async def _require_manager(self, manager_id: UUID | None) -> User | None:
        if manager_id is None:
            return None
        user = await self.access.get_user(manager_id)
        if user is None:
            raise ResourceNotFoundError("Manager not found")
        return user

    async def _upsert_address(
        self,
        address_id: UUID | None,
        payload: AddressPayload | None,
        *,
        address_type: AddressType = AddressType.BRANCH,
    ) -> UUID | None:
        if payload is None:
            return address_id
        values = _address_values(payload)
        if address_id is None:
            if not _address_has_values(payload):
                return None
            address = await self.org.create_address(values, address_type=address_type)
            return address.id
        updated = await self.org.update_address(address_id, values)
        if updated is None:
            address = await self.org.create_address(values, address_type=address_type)
            return address.id
        return updated.id

    async def _organization_response(self, org: Organization) -> OrganizationResponse:
        settings = OrganizationSettings.model_validate(org.settings or {})
        headquarters = None
        if org.headquarters_address_id is not None:
            address = await self.org.get_address(org.headquarters_address_id)
            headquarters = _address_response(address)
            if headquarters is not None:
                settings = settings.model_copy(update={"headquarters": AddressPayload.model_validate(headquarters)})
        return OrganizationResponse(
            id=org.id,
            name=org.name,
            timezone=org.timezone,
            logo_url=_logo_url(org.logo_storage_key),
            industry=org.industry or settings.industry,
            website=org.website or settings.website,
            contact_email=org.contact_email or settings.contact_email,
            phone=org.phone or settings.phone,
            fiscal_year_start_month=org.fiscal_year_start_month,
            fiscal_year_start_day=org.fiscal_year_start_day,
            settings=settings,
            users_count=await self.org.count_users(),
            departments_count=await self.org.count_departments(),
            branches_count=await self.org.count_branches(),
            created_at=org.created_at,
            updated_at=org.updated_at,
        )

    def _organization_snapshot(self, org: Organization) -> dict[str, object]:
        return {
            "name": org.name,
            "timezone": org.timezone,
            "industry": org.industry,
            "website": org.website,
            "contact_email": org.contact_email,
            "phone": org.phone,
            "fiscal_year_start_month": org.fiscal_year_start_month,
            "fiscal_year_start_day": org.fiscal_year_start_day,
            "has_logo": org.logo_storage_key is not None,
        }

    async def _branch_snapshot(self, branch: Branch) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "name": branch.name,
            "code": branch.code,
            "status": branch.status,
            "phone": branch.phone,
            "timezone": branch.timezone,
        }
        if branch.address_id is not None:
            address = await self.org.get_address(branch.address_id)
            label = format_address_label(_address_response(address))
            if label is not None:
                snapshot["address"] = label
        return snapshot

    async def _department_snapshot(self, department: Department) -> dict[str, object]:
        branch = await self.org.get_branch(department.branch_id)
        manager_name: str | None = None
        if department.manager_id is not None:
            users = await self.org.get_users_by_ids([department.manager_id])
            manager = users.get(department.manager_id)
            if manager is not None:
                manager_name = manager.name
        return {
            "name": department.name,
            "code": department.code,
            "branch": branch.name if branch is not None else None,
            "manager": manager_name,
        }

    async def _branch_responses(self, branches: list[Branch]) -> list[BranchResponse]:
        address_ids = [branch.address_id for branch in branches if branch.address_id is not None]
        addresses = await self.org.get_addresses(address_ids)
        counts = {
            branch.id: await self.org.count_users_for_branch(branch.id) for branch in branches
        }
        return [
            BranchResponse(
                id=branch.id,
                name=branch.name,
                code=branch.code,
                status=BranchStatus(branch.status),
                phone=branch.phone,
                timezone=branch.timezone,
                address=_address_response(addresses.get(branch.address_id))
                if branch.address_id is not None
                else None,
                user_count=counts.get(branch.id, 0),
                created_at=branch.created_at,
                updated_at=branch.updated_at,
            )
            for branch in branches
        ]

    async def _department_responses(self, departments: list[Department]) -> list[DepartmentResponse]:
        branch_ids = [department.branch_id for department in departments]
        manager_ids = [
            department.manager_id for department in departments if department.manager_id is not None
        ]
        branches = await self.org.get_branches_by_ids(branch_ids)
        managers = await self.org.get_users_by_ids(manager_ids)
        return [
            DepartmentResponse(
                id=department.id,
                name=department.name,
                code=department.code,
                branch_id=department.branch_id,
                branch=BranchSummary.model_validate(branches[department.branch_id])
                if department.branch_id in branches
                else None,
                manager_id=department.manager_id,
                manager=UserSummary.model_validate(managers[department.manager_id])
                if department.manager_id is not None and department.manager_id in managers
                else None,
                user_count=await self.org.count_users_for_department(department.id),
                created_at=department.created_at,
                updated_at=department.updated_at,
            )
            for department in departments
        ]
