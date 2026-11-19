"""Small admin CLI: create operator accounts and check Keitaro connectivity.

Passwords are always read interactively so they never land in shell history
or in the process list.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.container import build_container
from app.core.exceptions import AdrobotError
from app.core.security import hash_password
from app.db.models import User

MIN_PASSWORD_LENGTH = 12


async def _create_user(email: str, password: str) -> int:
    settings = get_settings()
    container = build_container(settings)
    try:
        async with container.session_factory() as session, session.begin():
            normalized = email.strip().lower()
            existing = await session.scalar(select(User).where(User.email == normalized))
            if existing is not None:
                existing.password_hash = hash_password(password)
                print(f"Password updated for {normalized}")
                return 0
            session.add(User(email=normalized, password_hash=hash_password(password)))
            print(f"Created user {normalized}")
            return 0
    finally:
        await container.aclose()


async def _check_keitaro() -> int:
    settings = get_settings()
    container = build_container(settings)
    try:
        offers = await container.catalog.offers()
        domains = await container.catalog.domains()
        groups = await container.catalog.groups()
        sources = await container.catalog.traffic_sources()
    except AdrobotError as exc:
        print(f"Keitaro check failed: {exc.safe_message}", file=sys.stderr)
        return 1
    finally:
        await container.aclose()

    print(f"Keitaro at {settings.keitaro_base_url} is reachable:")
    print(f"  offers:         {len(offers)}")
    print(f"  domains:        {len(domains)}")
    print(f"  groups:         {len(groups)}")
    print(f"  traffic sources:{len(sources)}")
    return 0


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        raise SystemExit(2)
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(2)
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="adrobot", description="Adrobot admin commands")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="Create or re-password an operator")
    create.add_argument("--email", required=True)

    commands.add_parser("check-keitaro", help="Verify Keitaro credentials and connectivity")

    args = parser.parse_args(argv)

    if args.command == "create-user":
        return asyncio.run(_create_user(args.email, _prompt_password()))
    return asyncio.run(_check_keitaro())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
