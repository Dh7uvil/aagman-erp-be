from collections.abc import Sequence

from app.core.enums import RecordScope

_SCOPE_RANK: dict[RecordScope, int] = {
    RecordScope.ALL: 0,
    RecordScope.BRANCH: 1,
    RecordScope.TEAM: 2,
    RecordScope.OWN: 3,
}


def effective_record_scope(scopes: Sequence[str | RecordScope]) -> RecordScope:
    if not scopes:
        return RecordScope.ALL
    parsed = [RecordScope(scope) for scope in scopes]
    return min(parsed, key=lambda scope: _SCOPE_RANK[scope])
