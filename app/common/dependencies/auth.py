from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import RecordScope, UserStatus
from app.core.exceptions import InvalidCredentialsError, InvalidTokenError
from app.core.middleware import set_user_id
from app.core.security import decode_access_token
from app.db.session import get_db
from app.identity.repository import AccessRepository

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: UUID
    permissions: frozenset[str] = frozenset()
    record_scope: RecordScope = RecordScope.ALL


def _parse_claim_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise InvalidTokenError() from exc


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidTokenError()

    settings = get_settings()
    claims = decode_access_token(
        credentials.credentials,
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    user_id = _parse_claim_uuid(claims.subject)
    if user_id is None:
        raise InvalidTokenError()

    repo = AccessRepository(session)
    user = await repo.get_user_by_id(user_id)
    if user is None:
        raise InvalidTokenError()
    if claims.token_version != user.token_version:
        raise InvalidTokenError()
    if user.status != UserStatus.ACTIVE:
        raise InvalidCredentialsError()

    permissions = await repo.list_user_permission_strings(user.id)
    record_scopes = await repo.list_user_record_scopes(user.id)
    set_user_id(str(user.id))
    from app.common.repositories.scoping import effective_record_scope

    return CurrentUser(
        user_id=user.id,
        permissions=permissions,
        record_scope=effective_record_scope(record_scopes),
    )


CurrentUserDependency = Annotated[CurrentUser, Depends(get_current_user)]
