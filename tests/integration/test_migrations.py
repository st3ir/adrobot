"""The Alembic migration chain must build the schema the ORM expects."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {"users", "campaign_records", "audit_log", "alembic_version"}


def run_alembic(command: str, database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *command.split()],
        cwd=PROJECT_ROOT,
        env={"PATH": "/usr/bin:/bin", "DATABASE_URL": database_url, "ENVIRONMENT": "local"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.slow
class TestMigrations:
    def test_upgrade_then_downgrade(self, tmp_path: Path) -> None:
        db_file = tmp_path / "migrated.db"
        async_url = f"sqlite+aiosqlite:///{db_file}"

        upgrade = run_alembic("upgrade head", async_url)
        assert upgrade.returncode == 0, upgrade.stderr

        engine = create_engine(f"sqlite:///{db_file}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        assert tables >= EXPECTED_TABLES

        downgrade = run_alembic("downgrade base", async_url)
        assert downgrade.returncode == 0, downgrade.stderr

        engine = create_engine(f"sqlite:///{db_file}")
        try:
            remaining = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        assert not remaining & {"users", "campaign_records", "audit_log"}
