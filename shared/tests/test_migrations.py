"""The one test in this repo that needs a real, pgvector-enabled Postgres.

SQLite can't validate `CREATE EXTENSION vector` or `vector(N)` DDL, so this
can't be mocked like the rest of the suite. Skipped unless
JARVIS_TEST_PGVECTOR_DATABASE_URL points at a throwaway database — run it
manually against a local Infra stack before merging schema changes, per
CLAUDE.md.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

DATABASE_URL = os.environ.get("JARVIS_TEST_PGVECTOR_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set JARVIS_TEST_PGVECTOR_DATABASE_URL to a live pgvector-enabled Postgres to run this",
)


def test_alembic_upgrade_head_runs_cleanly():
    shared_dir = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=shared_dir,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
