from datetime import date as DateType

from pydantic import BaseModel

from app.schemas.user import UserReference


class ActivityCreate(BaseModel):
    title: str
    description: str
    date: DateType
    sub_task_id: int


class ActivityUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    date: DateType | None = None
    status: str | None = None
    sub_task_id: int | None = None


class ActivityResponse(BaseModel):
    id: int
    title: str
    description: str
    date: DateType
    status: str
    sub_task_id: int
    created_by: UserReference

    class Config:
        from_attributes = True


class ActivityListResponse(BaseModel):
    items: list[ActivityResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
