from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.models.sub_task import SubTaskStatus
from app.schemas.user import UserReference


class SubTaskCreate(BaseModel):
    title: str
    description: str
    status: SubTaskStatus = SubTaskStatus.not_complete
    priority: Annotated[int, Field(ge=0, le=100)] = 0
    estimated_days: Annotated[int, Field(ge=0)] = 0
    estimated_hours: Annotated[int, Field(ge=0, lt=24)] = 0
    actual_days: Annotated[int, Field(ge=0)] = 0
    actual_hours: Annotated[int, Field(ge=0, lt=24)] = 0
    task_id: int


class SubTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: SubTaskStatus | None = None
    priority: Annotated[int, Field(ge=0, le=100)] | None = None
    estimated_days: Annotated[int, Field(ge=0)] | None = None
    estimated_hours: Annotated[int, Field(ge=0, lt=24)] | None = None
    actual_days: Annotated[int, Field(ge=0)] | None = None
    actual_hours: Annotated[int, Field(ge=0, lt=24)] | None = None
    task_id: int | None = None


class SubTaskResponse(BaseModel):
    id: int
    title: str
    description: str
    status: str
    priority: int
    estimated_days: int
    estimated_hours: int
    actual_days: int
    actual_hours: int
    created_at: datetime
    completed_at: datetime | None = None
    task_id: int
    created_by: UserReference

    class Config:
        orm_mode = True


class SubTaskListResponse(BaseModel):
    items: list[SubTaskResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
