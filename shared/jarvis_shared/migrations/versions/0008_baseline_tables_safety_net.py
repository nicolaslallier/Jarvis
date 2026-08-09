"""baseline tables safety net: create items/tasks/chat_sessions/chat_messages/folders/files if missing

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-09

Why this exists: 0001 ("baseline: pre-existing tables created via legacy
Base.metadata.create_all") is intentionally a no-op — it assumes
items/tasks/chat_sessions/chat_messages/folders/files already exist, because
on every environment that has actually run this app, they were created by
`Base.metadata.create_all` in backend/app/main.py's startup lifespan, not by
Alembic. That's fine for any database that has run the FastAPI app at least
once, but it means `alembic upgrade head` alone, from a truly empty database
that never ran `create_all` (a fresh CI/staging DB, for example), cannot
bootstrap these 6 tables — Alembic has no record of ever creating them, and
neither does anything else.

This migration is a pure, additive safety net for exactly that case: it
issues `CREATE TABLE IF NOT EXISTS` for all 6 baseline tables, reproducing
their CURRENT full column set (including every column added by 0002's
files.ingested_at and 0006/0007's task-enrichment columns) in one shot, since
this only matters for a database with none of the 6 tables yet and thus needs
the complete current shape, not the historical pre-0002/0006 shape. On any
database that already has these tables (i.e. every real environment today,
since they all ran `create_all`), every statement here is a guaranteed
no-op — `IF NOT EXISTS` short-circuits before touching anything.

This is NOT a replacement for `create_all`, and it does not make 0001
non-trivial: `create_all` is left running exactly as before (see
backend/app/main.py), and 0001/0002/0006/0007 are untouched. Fully retiring
`create_all` and making these tables Alembic-managed from empty would require
retrofitting `IF NOT EXISTS`/existence-guard logic into 0002's
`op.add_column` and 0006's `op.add_column`/`op.create_foreign_key`/backfill
statements, which currently assume the tables (and, transiently, columns like
the pre-0006 `tasks.done`/`tasks.due_date` that no longer exist anywhere in
current code) already exist in a specific historical shape. Retrofitting
that is real production-schema surgery on migrations that may have already
run against the live homelab Postgres, so it's deliberately out of scope
here — this migration only adds a fallback path for environments that have
never run `create_all` at all, it does not change behavior for any database
that already has these tables.

Table creation order below is FK-dependency safe: folders/items/chat_sessions
first (no dependencies on each other), then files (references folders), then
chat_messages (references chat_sessions), then tasks last (references files,
itself, and appointments — appointments is a *different* migration's table,
created by 0005, which has already run by the time 0008 runs in the revision
chain, so that FK target always exists). The `tasks` foreign key constraint
names (`fk_tasks_parent_id_tasks`, `fk_tasks_appointment_id_appointments`,
`fk_tasks_file_id_files`) intentionally match the names 0006's
`op.create_foreign_key` calls use, so that on the (out-of-scope, not fully
solved) hypothetical of this migration ever running first against a truly
empty database, 0006's later `op.create_foreign_key` calls for those same
names wouldn't collide.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No dependencies on any of the other 5 tables in this migration.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            parent_id INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_folders_parent_id_folders FOREIGN KEY (parent_id)
                REFERENCES folders (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL DEFAULT 'New chat',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # Needs folders (folder_id FK).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) NOT NULL,
            content_type VARCHAR(255),
            size BIGINT NOT NULL,
            object_key VARCHAR(512) NOT NULL UNIQUE,
            folder_id INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ingested_at TIMESTAMPTZ,
            CONSTRAINT fk_files_folder_id_folders FOREIGN KEY (folder_id)
                REFERENCES folders (id) ON DELETE CASCADE
        )
        """
    )

    # Needs chat_sessions (session_id FK).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_chat_messages_session_id_chat_sessions FOREIGN KEY (session_id)
                REFERENCES chat_sessions (id) ON DELETE CASCADE
        )
        """
    )

    # Last: needs files, itself (self-referencing), and appointments (already
    # created by migration 0005, earlier in this same revision chain).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            description VARCHAR(2000),
            due_at TIMESTAMPTZ,
            status VARCHAR(20) NOT NULL DEFAULT 'todo',
            priority VARCHAR(10) NOT NULL DEFAULT 'normal',
            completed_at TIMESTAMPTZ,
            project VARCHAR(100),
            tags JSON,
            parent_id INTEGER,
            recurrence_rule VARCHAR(255),
            appointment_id INTEGER,
            file_id INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT fk_tasks_parent_id_tasks FOREIGN KEY (parent_id)
                REFERENCES tasks (id) ON DELETE SET NULL,
            CONSTRAINT fk_tasks_appointment_id_appointments FOREIGN KEY (appointment_id)
                REFERENCES appointments (id) ON DELETE SET NULL,
            CONSTRAINT fk_tasks_file_id_files FOREIGN KEY (file_id)
                REFERENCES files (id) ON DELETE SET NULL
        )
        """
    )


def downgrade() -> None:
    # FK-safe reverse order: tasks and chat_messages reference other tables
    # in this migration, so they must go first; the remaining 4 have no
    # dependency on each other and can drop in any order.
    op.execute("DROP TABLE IF EXISTS tasks")
    op.execute("DROP TABLE IF EXISTS chat_messages")
    op.execute("DROP TABLE IF EXISTS files")
    op.execute("DROP TABLE IF EXISTS folders")
    op.execute("DROP TABLE IF EXISTS chat_sessions")
    op.execute("DROP TABLE IF EXISTS items")
