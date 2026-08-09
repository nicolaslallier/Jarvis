"""enrich tasks: status/priority/project/tags/subtasks/recurrence/due_at

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-09

"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("status", sa.String(length=20), nullable=True))
    op.add_column("tasks", sa.Column("priority", sa.String(length=10), nullable=True))
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("project", sa.String(length=100), nullable=True))
    op.add_column("tasks", sa.Column("tags", sa.JSON(), nullable=True))
    op.add_column("tasks", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_rule", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("appointment_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("file_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_tasks_parent_id_tasks", "tasks", "tasks", ["parent_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_tasks_appointment_id_appointments",
        "tasks",
        "appointments",
        ["appointment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tasks_file_id_files", "tasks", "files", ["file_id"], ["id"], ondelete="SET NULL"
    )

    # Backfill status/completed_at from the old `done` boolean, and due_at
    # from the old `due_date` (midnight on that date), before dropping them.
    op.execute("UPDATE tasks SET status = CASE WHEN done THEN 'done' ELSE 'todo' END")
    op.execute("UPDATE tasks SET priority = 'normal'")
    op.execute("UPDATE tasks SET completed_at = created_at WHERE done")
    op.execute("UPDATE tasks SET due_at = due_date::timestamptz WHERE due_date IS NOT NULL")

    op.alter_column("tasks", "status", nullable=False, server_default="todo")
    op.alter_column("tasks", "priority", nullable=False, server_default="normal")

    op.drop_column("tasks", "done")
    op.drop_column("tasks", "due_date")


def downgrade() -> None:
    op.add_column("tasks", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("tasks", sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.execute("UPDATE tasks SET due_date = due_at::date WHERE due_at IS NOT NULL")
    op.execute("UPDATE tasks SET done = (status = 'done')")

    op.drop_constraint("fk_tasks_file_id_files", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_appointment_id_appointments", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_parent_id_tasks", "tasks", type_="foreignkey")

    op.drop_column("tasks", "due_at")
    op.drop_column("tasks", "file_id")
    op.drop_column("tasks", "appointment_id")
    op.drop_column("tasks", "recurrence_rule")
    op.drop_column("tasks", "parent_id")
    op.drop_column("tasks", "tags")
    op.drop_column("tasks", "project")
    op.drop_column("tasks", "completed_at")
    op.drop_column("tasks", "priority")
    op.drop_column("tasks", "status")
