"""add habits/contacts/bills tables; appointments.source/pending_review; memories.source

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-09

Three new life-domain tables, plus two small additive columns on tables
that already exist. All four `frequency`/`date_type`/`recurrence`/`source`
columns below follow the exact free-string convention already established
by `tasks.status`/`tasks.priority` (see 0001/0006): a plain `String`
column with no DB-level `ENUM` type, validated (if at all) at the Pydantic
schema layer in `backend/app/schemas.py`. This schema has never used a
Postgres ENUM anywhere, and a free string is cheaper to extend later (a
new allowed value is a code-level constant change, not a migration) —
there's no reason to introduce the first one here.

--- habits ---

A simple recurring-habit tracker: name, how often it's meant to recur
(`frequency`, e.g. "daily"/"weekly" — free string, see above), a running
`streak_count`, and `last_completed_at` (NULL until first completion).
Streak-breaking/incrementing logic lives in application code (a batch job
or an API route), not in the schema — the table just stores the current
tally.

--- contacts ---

Deliberately ONE table for both "a contact" and "an important date about
them" (birthday, anniversary, a renewal date), not two separate `contacts`
+ `contact_dates` tables. A normalized split (one contact row owning many
date rows) would be the textbook design if this needed to track *multiple*
dates per person, but nothing in the current feature set asks for that —
every contact reminder in scope right now is exactly one person tied to
exactly one recurring date. Splitting it now would be premature
normalization: it adds a join, a second table, and a second FK to
maintain for a one-to-many relationship this app doesn't actually exercise
yet. If a future feature needs multiple dates per contact (e.g. both a
birthday and a work anniversary for the same person), that's a
straightforward later migration — add a `contact_dates` table and migrate
existing rows into it — not a reason to pay that complexity cost today.
`date_type` (free string: "birthday"/"anniversary"/"renewal"/...)
describes what the date represents; `recurring_yearly` defaults true since
birthdays/anniversaries recur every year, but is a real column (not
hardcoded) so a one-off reminder date can opt out; `reminder_lead_days`
controls how many days before the date a reminder should fire, defaulting
to a week out.

--- bills ---

Recurring-bill reminders only, in this pass — deliberately no paid/status
tracking (no `paid_at`, no `status` column, nothing marking a given
month's instance as settled). Adding that would mean modeling *instances*
of a recurring bill (one row per billing cycle, or a separate
`bill_payments` table), which is a materially bigger design question
(how do instances get generated — a batch job creating rows ahead of
time? computed on read from `due_day`/`recurrence`?) than this migration
is trying to answer. What's needed right now is just "remind me this bill
is coming due" — `amount`, `due_day` (day-of-month, paired with
`recurrence` describing the cycle, e.g. "monthly"/"yearly" — free string,
see above) is sufficient for that. Paid/status tracking is a deliberately
deferred follow-up, not an oversight.

--- appointments.source / appointments.pending_review ---

Both added for an email-ingestion feature that isn't built yet but whose
shape is already known: a future job will parse incoming emails and create
draft `Appointment` rows from anything that looks like a scheduled event,
without a human having confirmed it's real yet. `source` (free string,
e.g. "email_ingestion" vs. NULL/unset for appointments created directly by
the user through the app) records where a row came from; `pending_review`
(default false, so every appointment created through the existing manual
flow is unaffected) flags a draft row as needing the user's confirmation
before it should be treated as a real, trusted appointment (e.g. surfaced
in reminders/briefings). Both are nullable/defaulted so this migration is
purely additive against existing rows and the feature that reads them can
land in a later, separate change.

--- memories.source ---

Distinguishes journal entries the user writes directly (a future direct-
entry feature) from facts the chat model extracts from conversation via
`backend/app/memory.py`'s existing extraction path. NULL/unset preserves
the current meaning for every row written before this column existed
(all of them extracted from chat, per `memory.py`'s current only writer),
so this is purely additive; a future direct-journal-entry feature can set
an explicit value (e.g. "journal") without needing a backfill.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "habits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("streak_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("date_type", sa.String(length=20), nullable=False),
        sa.Column("recurring_yearly", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reminder_lead_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "bills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("recurrence", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.add_column("appointments", sa.Column("source", sa.String(length=50), nullable=True))
    op.add_column(
        "appointments",
        sa.Column("pending_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column("memories", sa.Column("source", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("memories", "source")

    op.drop_column("appointments", "pending_review")
    op.drop_column("appointments", "source")

    op.drop_table("bills")
    op.drop_table("contacts")
    op.drop_table("habits")
