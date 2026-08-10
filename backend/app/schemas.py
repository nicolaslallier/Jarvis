from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ItemCreate(BaseModel):
    name: str


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


TaskStatus = Literal["todo", "doing", "done", "cancelled", "pending_review"]
TaskPriority = Literal["low", "normal", "high"]


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    due_at: datetime | None = None
    priority: TaskPriority = "normal"
    status: TaskStatus = "todo"
    project: str | None = None
    tags: list[str] | None = None
    parent_id: int | None = None
    recurrence_rule: str | None = None
    appointment_id: int | None = None
    file_id: int | None = None

    @model_validator(mode="after")
    def _recurrence_requires_due_at(self) -> "TaskCreate":
        # A recurring task with no due_at has no anchor datetime for
        # task_service.complete_task to compute the next occurrence from —
        # reject that combination up front instead of letting it silently
        # produce a recurring task that can never regenerate.
        if self.recurrence_rule is not None and self.due_at is None:
            raise ValueError("due_at is required when recurrence_rule is set")
        return self


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    due_at: datetime | None
    status: TaskStatus
    priority: TaskPriority
    completed_at: datetime | None
    project: str | None
    tags: list[str] | None
    parent_id: int | None
    recurrence_rule: str | None
    appointment_id: int | None
    file_id: int | None
    created_at: datetime


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    due_at: datetime | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    project: str | None = None
    tags: list[str] | None = None
    parent_id: int | None = None
    recurrence_rule: str | None = None
    appointment_id: int | None = None
    file_id: int | None = None

    @model_validator(mode="after")
    def _recurrence_requires_due_at(self) -> "TaskUpdate":
        # Same rule as TaskCreate. TaskUpdate is a partial patch (routers
        # apply it via exclude_unset), so this only rejects a single request
        # that tries to set recurrence_rule and clear/omit due_at at the
        # same time — it can't see a due_at already stored from an earlier
        # request. Setting recurrence_rule together with due_at in the same
        # call (or on a task that already has one, by leaving due_at
        # untouched) both work; only turning recurrence on with due_at
        # explicitly None here is rejected.
        if self.recurrence_rule is not None and "due_at" in self.model_fields_set and self.due_at is None:
            raise ValueError("due_at cannot be cleared while recurrence_rule is set")
        return self


class AppointmentCreate(BaseModel):
    title: str
    description: str | None = None
    location: str | None = None
    start_time: datetime
    end_time: datetime
    all_day: bool = False


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    location: str | None
    start_time: datetime
    end_time: datetime
    all_day: bool
    # True = a draft row (e.g. from email_ingest, source="email_import")
    # awaiting user confirmation — see Appointment.pending_review's docstring
    # in shared/jarvis_shared/models.py. Exposed here so the frontend's
    # pending-review approval surface (TodayPage.tsx) can tell drafts apart
    # from real, confirmed appointments.
    pending_review: bool
    created_at: datetime
    updated_at: datetime


class AppointmentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    all_day: bool | None = None
    # Lets the approval flow flip a draft appointment to confirmed
    # (pending_review: false) via the existing PUT endpoint rather than a
    # dedicated confirm route.
    pending_review: bool | None = None


class ChatSessionCreate(BaseModel):
    title: str | None = None


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["system", "user", "assistant"]
    content: str
    created_at: datetime


class ChatSessionDetail(ChatSessionRead):
    messages: list[ChatMessageRead]


class ChatSendRequest(BaseModel):
    content: str


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    session_id: int | None
    created_at: datetime


class MemoryUpdate(BaseModel):
    content: str


class MemoryCreate(BaseModel):
    """POST /memories body — the user writing a journal/quick-note directly
    (source='journal' on the resulting row), as opposed to a fact the chat
    model extracted from a conversation."""

    content: str


class MemoryCreateRead(BaseModel):
    """Response for POST /memories. Deliberately narrower than MemoryRead
    (no session_id/source): a journal note has no session_id, and the
    caller already knows source='journal' since that's what it just asked
    to create."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    created_at: datetime


SearchResultKind = Literal[
    "task", "appointment", "file_chunk", "memory", "chat_message", "meeting_summary"
]


class SearchResultRead(BaseModel):
    kind: SearchResultKind
    id: int
    title: str
    snippet: str
    # None for ILIKE-based kinds (task/appointment/chat_message), which have
    # no notion of relevance ranking; the raw cosine distance (lower =
    # closer) for vector-based kinds (file_chunk/memory). Deliberately never
    # unified into one comparable number across kinds — see
    # app/search_service.py's module docstring.
    score: float | None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultRead]


class BriefingRead(BaseModel):
    date: str
    appointments: list[AppointmentRead]
    due_tasks: list[TaskRead]
    overdue_tasks: list[TaskRead]
    summary: str | None


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str | None
    size: int
    folder_id: int | None
    created_at: datetime
    ingested_at: datetime | None


HabitFrequency = Literal["daily", "weekly"]


class HabitCreate(BaseModel):
    name: str
    frequency: HabitFrequency


class HabitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    frequency: str
    streak_count: int
    last_completed_at: datetime | None
    created_at: datetime


BillRecurrence = Literal["monthly", "yearly"]


class BillCreate(BaseModel):
    name: str
    amount: Decimal
    # Day-of-month the bill is due. For "yearly" bills, the month is taken
    # from created_at (see batch/app/jobs/upcoming_bills.py) — only the day
    # is stored here, same convention for both recurrences.
    due_day: int = Field(ge=1, le=31)
    recurrence: BillRecurrence


class BillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    amount: Decimal
    due_day: int
    recurrence: str
    created_at: datetime


class BillUpdate(BaseModel):
    name: str | None = None
    amount: Decimal | None = None
    due_day: int | None = Field(default=None, ge=1, le=31)
    recurrence: BillRecurrence | None = None


# Aliased so the `date` field below (named to match Contact.date, the ORM
# column) doesn't shadow the `date` type in its own annotation once a class
# attribute of the same name exists (any field with a default, e.g.
# ContactUpdate's `date: date | None = None`) — pydantic v2 resolves forward
# ref annotations using the class namespace, where an assigned class
# attribute named `date` would otherwise shadow the imported type and break
# evaluation of `date | None`.
_ContactDate = date


class ContactCreate(BaseModel):
    name: str
    date: _ContactDate
    # Free string (e.g. "birthday"/"anniversary"/"renewal"), same no-DB-enum
    # convention as Task.status/Habit.frequency/Bill.recurrence.
    date_type: str
    recurring_yearly: bool = True
    reminder_lead_days: int = 7


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    date: _ContactDate
    date_type: str
    recurring_yearly: bool
    reminder_lead_days: int
    created_at: datetime


class ContactUpdate(BaseModel):
    name: str | None = None
    date: _ContactDate | None = None
    date_type: str | None = None
    recurring_yearly: bool | None = None
    reminder_lead_days: int | None = None


class MeetingSummaryCreate(BaseModel):
    title: str
    meeting_date: datetime
    content: str
    participants: str | None = None
    appointment_id: int | None = None


class MeetingSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    meeting_date: datetime
    participants: str | None
    content: str
    appointment_id: int | None
    created_at: datetime
    updated_at: datetime


class MeetingSummaryUpdate(BaseModel):
    title: str | None = None
    meeting_date: datetime | None = None
    content: str | None = None
    participants: str | None = None
    appointment_id: int | None = None


class FolderCreate(BaseModel):
    name: str
    parent_id: int | None = None


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None
    created_at: datetime
