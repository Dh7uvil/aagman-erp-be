"""Application enumerations."""

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    DISABLED = "DISABLED"


class RecordScope(StrEnum):
    ALL = "all"
    BRANCH = "branch"
    TEAM = "team"
    OWN = "own"


class BranchStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AddressType(StrEnum):
    BRANCH = "BRANCH"
    HEADQUARTERS = "HEADQUARTERS"
    WAREHOUSE = "WAREHOUSE"
    OTHER = "OTHER"


class AuditAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    APPROVE = "APPROVE"
    POST = "POST"
    CANCEL = "CANCEL"


class AuditStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


SYSTEM_ADMIN_ROLE_NAME = "Superadmin"
IDENTITY_MODULE = "identity"
