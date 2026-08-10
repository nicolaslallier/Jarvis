"""add notifications_sent table

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-09

This table exists to make "have we already notified the user about this
thing today" a single indexed lookup/insert instead of ad-hoc logic
scattered across whichever batch job sends reminders. `kind` is a free
string identifying the *type* of thing being notified about (e.g.
"task_due", "appointment_reminder" — more kinds land as more reminder
features do), `entity_id` is the primary key of that thing in its own
table (tasks.id, appointments.id, etc.), and `notified_date` is the
calendar date the notification was sent for. The UNIQUE constraint on
(kind, entity_id, notified_date) is what actually enforces "at most one
notification per thing per day" — a batch job can blindly try to INSERT
before sending and treat a unique-violation as "already sent, skip",
without needing a separate SELECT-then-INSERT check (and the race
condition that pattern would invite if a job ever runs concurrently with
itself).

Deliberately no foreign key from `entity_id` to `tasks.id`/`appointments.
id`/etc: `entity_id` doesn't point at one fixed table, it points at
whatever table `kind` says it does, and Postgres FKs can't be
conditional/polymorphic like that without a lot of extra machinery
(a discriminated set of nullable FK columns, or a trigger-enforced
polymorphic-association pattern) that this app doesn't need yet. More
importantly, even if `kind` were split into one column per entity type,
we deliberately would *not* want an ON DELETE CASCADE here: a task or
appointment can legitimately be deleted after the user has already been
notified about it (e.g. they saw the reminder, then deleted the task), and
at that point the notifications_sent row has already done its job — it
just needs to keep existing so we don't re-notify if a same-named/reused
id ever came back into play, or simply so the "was this ever notified"
history stays intact. A dangling row with an entity_id that no longer
resolves to a live task/appointment is harmless (nothing joins against it
for anything other than the exact-match dedupe check above), and is far
cheaper than building and maintaining cross-table cascade-delete tracking
for a purely advisory log table.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications_sent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("notified_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "kind", "entity_id", "notified_date", name="uq_notifications_sent_kind_entity_id_date"
        ),
    )


def downgrade() -> None:
    op.drop_table("notifications_sent")
