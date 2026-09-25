"""Mint a local development token (auth_mode=local only).

    python -m documind.scripts.dev_token --user alice

Paste the printed token into the "Authorize" button at http://localhost:8000/docs, or send it
as ``Authorization: Bearer <token>``. Different --user values are different, isolated tenants.
"""

import argparse
from pathlib import Path

from documind.core.auth import LocalAuthenticator
from documind.core.config import AuthMode, Settings


def load_settings() -> Settings:
    # Works from the repo root or from backend/.
    for candidate in (Path(".env"), Path("backend/.env")):
        if candidate.exists():
            return Settings(_env_file=candidate)
    return Settings()


def mint(user_id: str, ttl_hours: float = 12) -> str:
    settings = load_settings()
    if settings.auth_mode is not AuthMode.LOCAL or settings.jwt_secret is None:
        raise SystemExit("Dev tokens need auth_mode=local and DOCUMIND_JWT_SECRET set.")
    return LocalAuthenticator(settings.jwt_secret.get_secret_value()).issue(
        user_id, int(ttl_hours * 3600)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="alice")
    parser.add_argument("--hours", type=float, default=12)
    args = parser.parse_args()
    print(mint(args.user, args.hours))


if __name__ == "__main__":
    main()
