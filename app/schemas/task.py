from datetime import datetime
from typing import Annotated,Optional

from pydantic import BaseModel, Field, root_validator

from app.models.sub_task import SubTaskStatus
from app.models.task import TaskStatus
from app.schemas.sub_task import SubTaskResponse
from app.schemas.user import UserReference


class TaskSubTaskCreate(BaseModel):
    title: str
    description: str
    status: SubTaskStatus = SubTaskStatus.not_complete
    estimated_days: Annotated[int, Field(ge=0)] = 0
    estimated_hours: Annotated[int, Field(ge=0, lt=24)] = 0


class TaskCreate(BaseModel):
    title: str
    description: str
    start_date: datetime
    end_date: datetime
    assigned_to: int | None = None
    assigned_to_username: str | None = None
    sub_tasks: list[TaskSubTaskCreate] | None = None
    sub_task_count: Annotated[int, Field(ge=0)] | None = None

    @root_validator(skip_on_failure=True)
    def validate_sub_task_count(cls, values):
        sub_tasks = values.get("sub_tasks")
        sub_task_count = values.get("sub_task_count")

        if sub_task_count is not None and sub_tasks is None:
            raise ValueError("sub_task_count requires sub_tasks payload")

        if sub_task_count is not None and len(sub_tasks) != sub_task_count:
            raise ValueError("sub_task_count must match number of sub_tasks")

        return values


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    start_date: datetime
    end_date: datetime
    status: TaskStatus
    estimated_days: int
    estimated_hours: int
    created_by: UserReference
    assigned_to: Optional[UserReference]
    version: int
    parent_task_id: int | None = None

    class Config:
        orm_mode = True


class TaskCreateResponse(TaskResponse):
    sub_tasks: list[SubTaskResponse] = Field(default_factory=list)
    sub_tasks_created_count: int = 0


class TaskWithSubTasksResponse(TaskResponse):
    sub_tasks: list[SubTaskResponse] = Field(default_factory=list)


class TaskAdminResponse(BaseModel):
    id: int
    title: str
    description: str
    start_date: datetime
    end_date: datetime
    status: TaskStatus
    estimated_days: int
    estimated_hours: int
    created_by: UserReference
    assigned_to: UserReference

    class Config:
        orm_mode = True


class TaskListResponse(BaseModel):
    items: list[TaskWithSubTasksResponse]
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
    status: TaskStatus | None = None
    assigned_to: int | None = None
    assigned_to_username: str | None = None
