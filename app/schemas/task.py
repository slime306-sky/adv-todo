<<<<<<< HEAD
from datetime import datetime

from pydantic import BaseModel


class TaskCreate(BaseModel):
    title: str
    description: str
    start_date: datetime
    end_date: datetime
    assigned_to: int | None = None
    assigned_to_username: str | None = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    start_date: datetime
    end_date: datetime
    status: str
    estimated_days: int
    estimated_hours: int
    created_by: int
    assigned_to: int
    version: int
    parent_task_id: int | None = None

    class Config:
        orm_mode = True


class TaskAdminResponse(BaseModel):
    id: int
    title: str
    description: str
    status: str
    estimated_days: int
    estimated_hours: int
    creator_username: str
    assignee_username: str

    class Config:
        orm_mode = True


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TaskAdminListResponse(BaseModel):
    items: list[TaskAdminResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TaskProgressResponse(BaseModel):
    task_id: int
    total_subtasks: int
    completed_subtasks: int
    progress_percentage: float
    is_completed: bool


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    status: str | None = None
    assigned_to: int | None = None
    assigned_to_username: str | None = None
=======
from datetime import datetime

from pydantic import BaseModel


class TaskCreate(BaseModel):
    title: str
    description: str
    start_date: datetime
    end_date: datetime
    assigned_to: int | None = None
    assigned_to_username: str | None = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    start_date: datetime
    end_date: datetime
    status: str
    estimated_days: int
    estimated_hours: int
    created_by: int
    assigned_to: int
    version: int
    parent_task_id: int | None = None

    class Config:
        orm_mode = True


class TaskAdminResponse(BaseModel):
    id: int
    title: str
    description: str
    status: str
    estimated_days: int
    estimated_hours: int
    creator_username: str
    assignee_username: str

    class Config:
        orm_mode = True


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TaskAdminListResponse(BaseModel):
    items: list[TaskAdminResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TaskProgressResponse(BaseModel):
    task_id: int
    total_subtasks: int
    completed_subtasks: int
    progress_percentage: float
    is_completed: bool


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    status: str | None = None
    assigned_to: int | None = None
    assigned_to_username: str | None = None
>>>>>>> 9c962f1627ff7435b1f0ba63448f07959fba9ec1
