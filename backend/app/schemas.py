from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ItemCreate(BaseModel):
    name: str


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    due_date: date | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    due_date: date | None
    done: bool
    created_at: datetime


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
