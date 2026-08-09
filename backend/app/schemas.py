from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ItemCreate(BaseModel):
    name: str


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


TaskStatus = Literal["todo", "doing", "done", "cancelled"]
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
    created_at: datetime
    updated_at: datetime


class AppointmentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    all_day: bool | None = None


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


class ChatSendResponse(BaseModel):
    session: ChatSessionRead
    user_message: ChatMessageRead
    assistant_message: ChatMessageRead


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str | None
    size: int
    folder_id: int | None
    created_at: datetime
    ingested_at: datetime | None


class FolderCreate(BaseModel):
    name: str
    parent_id: int | None = None


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None
    created_at: datetime
