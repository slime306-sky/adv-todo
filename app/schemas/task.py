from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, root_validator

from app.models.sub_task import SubTaskStatus
from app.models.task import TaskStatus
from app.schemas.sub_task import SubTaskResponse
from app.schemas.user import UserReference


class TaskSubTaskCreate(BaseModel):
    title: str
    description: str
    status: SubTaskStatus = SubTaskStatus.not_complete
    priority: Annotated[int, Field(ge=0, le=100)] = 0
    estimated_days: Annotated[int, Field(ge=0)] = 0
    estimated_hours: Annotated[int, Field(ge=0, lt=24)] = 0
    start_date: datetime
    actual_days: Annotated[int, Field(ge=0)] = 0
    actual_hours: Annotated[int, Field(ge=0, lt=24)] = 0
    assigned_to: int | None = None
    assigned_to_username: str | None = None


class TaskCreate(BaseModel):
    title: str
    description: str
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
    status: TaskStatus
    estimated_days: int
    estimated_hours: int
    start_date: datetime | None = None
    end_date: datetime | None = None
    created_by: UserReference
    version: str
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
    status: TaskStatus
    estimated_days: int
    estimated_hours: int
    start_date: datetime | None = None
    end_date: datetime | None = None
    created_by: UserReference

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


class TimelineBar(BaseModel):
    key: str
    label: str
    hours: float
    percentage: float


class SubTaskTimelineItem(BaseModel):
    sub_task_id: int
    title: str
    status: str
    priority: int
    estimated_hours: float
    actual_hours: float
    expected_hours: float


class TaskTimelineResponse(BaseModel):
    task_id: int
    task_title: str
    total_estimated_hours: float
    total_actual_hours: float
    total_expected_hours: float
    bars: list[TimelineBar]
    sub_tasks: list[SubTaskTimelineItem]


class SubTaskPriorityItem(BaseModel):
    sub_task_id: int
    priority: Annotated[int, Field(ge=0, le=100)]


class TaskPriorityBulkUpdateRequest(BaseModel):
    items: list[SubTaskPriorityItem] = Field(default_factory=list)


class TaskPriorityBulkUpdateResponse(BaseModel):
    task_id: int
    total_priority: int
    items: list[SubTaskPriorityItem]


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None


class TaskVersionBumpRequest(BaseModel):
    bump_type: Literal["major", "minor", "patch"] = "patch"


class TaskUpdateRequestDecision(BaseModel):
    comment: str | None = None


class TaskUpdateRequestResponse(BaseModel):
    id: int
    task_id: int
    requested_by: UserReference
    status: str
    requested_changes: dict
    review_comment: str | None = None
    reviewed_by: UserReference | None = None
    created_at: datetime
    reviewed_at: datetime | None = None


class TaskUpdateRequestListResponse(BaseModel):
    items: list[TaskUpdateRequestResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
