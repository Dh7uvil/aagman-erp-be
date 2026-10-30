"""Request and response schemas for the access-management slice."""

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import (
    blank_to_none,
    normalize_required_text,
)
from app.core.enums import BranchStatus, UserStatus

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 72


def validate_password_strength(password: str) -> str:
    """Enforce minimum complexity for create, change, and reset flows."""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if not any(character.isupper() for character in password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(character.islower() for character in password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(character.isdigit() for character in password):
        raise ValueError("Password must contain at least one digit")
    return password


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise ValueError("email must be a valid email address")
    if len(normalized) > 255:
        raise ValueError("email must be at most 255 characters")
    return normalized


def _normalize_optional_phone(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)


class AdminResetUserPasswordRequest(BaseModel):
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class ForgotPasswordResponse(BaseModel):
    """Always the same public message. ``reset_token`` is testing-only."""

    message: str
    reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RoleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_system_role: bool


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class AddressPayload(BaseModel):
    address_line_1: str | None = Field(default=None, max_length=250)
    address_line_2: str | None = Field(default=None, max_length=250)
    address_line_3: str | None = Field(default=None, max_length=250)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    country_code: str | None = Field(default=None, max_length=10)
    postal_code: str | None = Field(default=None, max_length=30)

    @field_validator(
        "address_line_1",
        "address_line_2",
        "address_line_3",
        "city",
        "state",
        "country",
        "country_code",
        "postal_code",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AddressResponse(AddressPayload):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


def format_address_label(address: AddressResponse | None) -> str | None:
    """Human-readable address line for audit snapshots."""

    if address is None:
        return None
    parts = [
        address.address_line_1,
        address.address_line_2,
        address.city,
        address.state,
        address.postal_code,
        address.country,
    ]
    text = ", ".join(part for part in parts if part)
    return text or None


class BranchSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str


class DepartmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    phone: str | None
    status: UserStatus
    designation: str | None
    branch_id: UUID | None
    department_id: UUID | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleSummary] = Field(default_factory=list)
    branch: BranchSummary | None = None
    department: DepartmentSummary | None = None


class UserDetailResponse(UserResponse):
    roles: list[RoleSummary] = Field(default_factory=list)


class MeResponse(UserDetailResponse):
    permissions: list[str] = Field(default_factory=list)


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    phone: str | None = Field(default=None, max_length=50)
    status: UserStatus = UserStatus.ACTIVE
    role_ids: list[UUID] = Field(default_factory=list)
    branch_id: UUID | None = None
    department_id: UUID | None = None
    designation: str | None = Field(default=None, max_length=150)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)

    @field_validator("designation")
    @classmethod
    def normalize_designation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    status: UserStatus | None = None
    branch_id: UUID | None = None
    department_id: UUID | None = None
    designation: str | None = Field(default=None, max_length=150)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_email(value)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)

    @field_validator("designation")
    @classmethod
    def normalize_designation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AssignRolesRequest(BaseModel):
    role_ids: list[UUID]


class UserFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "email", "status", "last_login_at"}
    )

    status: UserStatus | None = Field(
        default=None,
        description="Account status: ACTIVE, INVITED, DISABLED.",
    )
    role_id: UUID | None = Field(
        default=None,
        description="Users assigned to this role. Combined with role_ids when both are set.",
    )
    role_ids: list[UUID] | None = Field(
        default=None,
        description="Users assigned to any of these roles.",
    )
    branch_id: UUID | None = Field(
        default=None,
        description="Users assigned to this branch.",
    )
    department_id: UUID | None = Field(
        default=None,
        description="Users assigned to this department.",
    )
    designation: str | None = Field(
        default=None,
        max_length=150,
        description="Case-insensitive match on user designation.",
    )
    phone: str | None = Field(
        default=None,
        max_length=50,
        description="Case-insensitive match on user phone.",
    )
    last_login_from: datetime | None = Field(
        default=None,
        description="Users whose last_login_at is on or after this timestamp.",
    )
    last_login_to: datetime | None = Field(
        default=None,
        description="Users whose last_login_at is on or before this timestamp.",
    )

    @field_validator("designation", "phone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("role_ids", mode="before")
    @classmethod
    def parse_role_ids(cls, value: object) -> object:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return parts or None
        if isinstance(value, UUID):
            return [value]
        if isinstance(value, (list, tuple)):
            return list(value)
        return None

    @model_validator(mode="after")
    def validate_last_login_range(self) -> "UserFilter":
        if (
            self.last_login_from is not None
            and self.last_login_to is not None
            and self.last_login_from > self.last_login_to
        ):
            raise ValueError("last_login_from must be before or equal to last_login_to")
        return self

    def collected_role_ids(self) -> list[UUID]:
        unique: dict[UUID, None] = {role_id: None for role_id in self.role_ids or []}
        if self.role_id is not None:
            unique[self.role_id] = None
        return list(unique)


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    is_system_role: bool
    record_scope: str
    user_count: int = 0
    created_at: datetime
    updated_at: datetime


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    module: str
    resource: str
    action: str
    created_at: datetime
    updated_at: datetime
    code: str = ""

    @model_validator(mode="after")
    def populate_code(self) -> "PermissionResponse":
        self.code = f"{self.module}.{self.resource}.{self.action}"
        return self


class RoleDetailResponse(RoleResponse):
    permissions: list[PermissionResponse] = Field(default_factory=list)


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    record_scope: str = Field(default="all", pattern="^(all|branch|team|own)$")
    permission_ids: list[UUID] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    record_scope: str | None = Field(default=None, pattern="^(all|branch|team|own)$")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SetRolePermissionsRequest(BaseModel):
    permission_ids: list[UUID]


class RoleFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})


class PermissionFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "module", "resource", "action"}
    )

    module: str | None = None


class PermissionMatrixAction(BaseModel):
    id: UUID
    action: str
    code: str
    granted: bool


class PermissionMatrixResource(BaseModel):
    resource: str
    actions: list[PermissionMatrixAction]


class PermissionMatrixModule(BaseModel):
    module: str
    resources: list[PermissionMatrixResource]


class PermissionMatrixResponse(BaseModel):
    modules: list[PermissionMatrixModule]


class OrganizationSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    industry: str | None = Field(default=None, max_length=150)
    website: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    headquarters: AddressPayload | None = None

    @field_validator("industry", "website", "phone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("contact_email")
    @classmethod
    def normalize_contact_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "@" not in normalized:
            raise ValueError("contact_email must be a valid email address")
        return normalized


class OrganizationBrandingResponse(BaseModel):
    """Public org name and logo for unauthenticated surfaces (e.g. login)."""

    name: str
    logo_url: str | None = None


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    timezone: str
    logo_url: str | None = None
    industry: str | None = None
    website: str | None = None
    contact_email: str | None = None
    phone: str | None = None
    fiscal_year_start_month: int = 1
    fiscal_year_start_day: int = 1
    settings: OrganizationSettings = Field(default_factory=OrganizationSettings)
    users_count: int
    departments_count: int
    branches_count: int
    created_at: datetime
    updated_at: datetime


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    industry: str | None = Field(default=None, max_length=150)
    website: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    fiscal_year_start_day: int | None = Field(default=None, ge=1, le=31)
    headquarters: AddressPayload | None = None
    settings: OrganizationSettings | None = None

    @field_validator(
        "timezone",
        "industry",
        "website",
        "contact_email",
        "phone",
        mode="before",
    )
    @classmethod
    def coerce_blank_optional_text(cls, value: object) -> object:
        return blank_to_none(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("timezone", "industry", "website", "phone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("contact_email")
    @classmethod
    def normalize_contact_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "@" not in normalized:
            raise ValueError("contact_email must be a valid email address")
        return normalized


class BranchFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code", "status"}
    )

    status: BranchStatus | None = None


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=50)
    status: BranchStatus = BranchStatus.ACTIVE
    phone: str | None = Field(default=None, max_length=50)
    timezone: str | None = Field(default=None, max_length=100)
    address: AddressPayload | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="code")

    @field_validator("phone", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    status: BranchStatus | None = None
    phone: str | None = Field(default=None, max_length=50)
    timezone: str | None = Field(default=None, max_length=100)
    address: AddressPayload | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="code")

    @field_validator("phone", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class BranchResponse(BaseModel):
    id: UUID
    name: str
    code: str
    status: BranchStatus
    phone: str | None
    timezone: str | None
    address: AddressResponse | None = None
    user_count: int = 0
    created_at: datetime
    updated_at: datetime


class DepartmentFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code"}
    )

    branch_id: UUID | None = None


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    branch_id: UUID
    manager_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="code")


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    branch_id: UUID | None = None
    manager_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="code")


class DepartmentResponse(BaseModel):
    id: UUID
    name: str
    code: str
    branch_id: UUID
    branch: BranchSummary | None = None
    manager_id: UUID | None
    manager: UserSummary | None = None
    user_count: int = 0
    created_at: datetime
    updated_at: datetime


class AuditLogFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "action", "module"})

    module: str | None = None
    action: str | None = None
    user_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None


class AuditLogUserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class AuditLogResponse(BaseModel):
    id: UUID
    timestamp: datetime
    user: AuditLogUserSummary | None = None
    action: str
    entity_type: str
    entity_id: UUID | None
    module: str
    ip_address: str | None
    status: str


class AuditLogChange(BaseModel):
    field: str
    old_value: Any = None
    new_value: Any = None


class AuditLogDetailResponse(AuditLogResponse):
    user_agent: str | None = None
    old_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    changes: list[AuditLogChange]


class AuditLogSummaryResponse(BaseModel):
    total_events: int
    unique_users: int
    failed_attempts: int
    admin_actions: int


def _normalize_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if "@" not in normalized:
        raise ValueError("email must be a valid email address")
    if len(normalized) > 255:
        raise ValueError("email must be at most 255 characters")
    return normalized


class CompanyFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "email"}
    )


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: AddressPayload | None = None
    bill_to_address: AddressPayload | None = None
    ship_to_address: AddressPayload | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return _normalize_optional_email(value)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: AddressPayload | None = None
    bill_to_address: AddressPayload | None = None
    ship_to_address: AddressPayload | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return _normalize_optional_email(value)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)


class CompanyResponse(BaseModel):
    id: UUID
    name: str
    email: str | None
    phone: str | None
    address: AddressResponse | None = None
    bill_to_address: AddressResponse | None = None
    ship_to_address: AddressResponse | None = None
    created_at: datetime
    updated_at: datetime


class WarehouseFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code"}
    )


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    is_default: bool = False
    is_active: bool = True
    address: AddressPayload | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="code")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)


class WarehouseUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    is_default: bool | None = None
    is_active: bool | None = None
    address: AddressPayload | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="code")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)


class WarehouseResponse(BaseModel):
    id: UUID
    code: str
    name: str
    phone: str | None
    is_default: bool
    is_active: bool
    address: AddressResponse | None = None
    created_at: datetime
    updated_at: datetime
