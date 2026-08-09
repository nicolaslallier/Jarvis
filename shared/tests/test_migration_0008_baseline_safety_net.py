"""Lightweight checks for 0008_baseline_tables_safety_net.

This migration's actual DDL (`CREATE TABLE IF NOT EXISTS` with Postgres-only
syntax like SERIAL/TIMESTAMPTZ) can't be executed against SQLite the way
shared/tests/test_models.py's pure-metadata checks can — SQLite doesn't
support that flavor of raw SQL identically to Postgres, and this migration
deliberately isn't ORM-metadata-driven (see its module docstring for why it
uses raw `op.execute` instead of `op.create_table`). Real end-to-end
execution of this (and every other) migration is already covered by
shared/tests/test_migrations.py's `alembic upgrade head` test, which is
skipped unless JARVIS_TEST_PGVECTOR_DATABASE_URL points at a live
pgvector-enabled Postgres — per CLAUDE.md, run that manually before merging
schema changes.

So this file sticks to static assertions: revision/down_revision chain
identity, and that the upgrade/downgrade SQL text mentions the right tables,
in FK-safe order, with the FK constraint names 0006 expects.
"""

import importlib.util
import inspect
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "jarvis_shared"
    / "migrations"
    / "versions"
    / "0008_baseline_tables_safety_net.py"
)


def _load_migration_module():
    # The file's name starts with a digit, so it can't be imported with a
    # normal `import` statement (not a valid Python identifier) — load it
    # directly from its path instead, same as Alembic itself does internally.
    spec = importlib.util.spec_from_file_location("migration_0008", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain():
    module = _load_migration_module()
    assert module.revision == "0008"
    assert module.down_revision == "0007"
    assert module.branch_labels is None
    assert module.depends_on is None


def test_upgrade_creates_all_six_tables_idempotently_in_dependency_order():
    module = _load_migration_module()
    source = inspect.getsource(module.upgrade)

    tables = ["folders", "items", "chat_sessions", "files", "chat_messages", "tasks"]
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source, f"missing IF NOT EXISTS create for {table}"

    # FK-dependency-safe order: folders before files (files.folder_id -> folders),
    # chat_sessions before chat_messages (chat_messages.session_id -> chat_sessions),
    # and files/chat_messages before tasks (tasks.file_id -> files; tasks also
    # self-references and references appointments, which is a prior migration's
    # table and not created here).
    positions = {table: source.index(f"CREATE TABLE IF NOT EXISTS {table}") for table in tables}
    assert positions["folders"] < positions["files"]
    assert positions["chat_sessions"] < positions["chat_messages"]
    assert positions["files"] < positions["tasks"]
    assert positions["chat_messages"] < positions["tasks"]


def test_upgrade_tasks_fk_names_match_0006():
    module = _load_migration_module()
    source = inspect.getsource(module.upgrade)

    # Must match the constraint names 0006_task_enrichment.py's
    # op.create_foreign_key calls use, so the two migrations can never
    # collide on constraint naming.
    for fk_name in (
        "fk_tasks_parent_id_tasks",
        "fk_tasks_appointment_id_appointments",
        "fk_tasks_file_id_files",
    ):
        assert fk_name in source


def test_downgrade_drops_all_six_tables_with_dependents_first():
    module = _load_migration_module()
    source = inspect.getsource(module.downgrade)

    tables = ["folders", "items", "chat_sessions", "files", "chat_messages", "tasks"]
    for table in tables:
        assert f"DROP TABLE IF EXISTS {table}" in source, f"missing IF EXISTS drop for {table}"

    positions = {table: source.index(f"DROP TABLE IF EXISTS {table}") for table in tables}
    # tasks and chat_messages reference other tables in this migration, so
    # they must be dropped before the tables they depend on.
    assert positions["tasks"] < positions["files"]
    assert positions["chat_messages"] < positions["chat_sessions"]
