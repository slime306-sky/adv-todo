from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.models.sub_task import SubTaskStatus
from app.schemas.user import UserReference


class SubTaskCreate(BaseModel):
    title: str
    description: str
    status: SubTaskStatus = SubTaskStatus.not_complete
    estimated_days: Annotated[int, Field(ge=0)] = 0
    estimated_hours: Annotated[int, Field(ge=0, lt=24)] = 0
    task_id: int


class SubTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: SubTaskStatus | None = None
    estimated_days: Annotated[int, Field(ge=0)] | None = None
    estimated_hours: Annotated[int, Field(ge=0, lt=24)] | None = None
    task_id: int | None = None


class SubTaskResponse(BaseModel):
    id: int
    title: str
    description: str
    status: str
    estimated_days: int
    estimated_hours: int
    created_at: datetime
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
