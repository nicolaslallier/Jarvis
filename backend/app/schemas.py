from datetime import date, datetime

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
