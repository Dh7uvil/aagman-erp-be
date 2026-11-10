"""Generate a random JWT secret suitable for .env."""

from __future__ import annotations

import secrets


def main() -> None:
    print(secrets.token_urlsafe(48))


if __name__ == "__main__":
    main()
