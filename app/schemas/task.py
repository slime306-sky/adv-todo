from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, root_validator

from app.models.sub_task import SubTaskPriority, SubTaskStatus
from app.models.task import TaskStatus
from app.schemas.category import CategoryReference
from app.schemas.sub_task import SubTaskResponse
from app.schemas.user import DepartmentReference, UserReference


class TaskSubTaskBase(BaseModel):
    model_config = {"populate_by_name": True}

    title: str
    description: str
    status: SubTaskStatus = SubTaskStatus.not_complete
    weightage_priority: Annotated[int, Field(ge=0, le=10)] | None = None
    subtask_priority: SubTaskPriority | None = None
    estimated_days: Annotated[int, Field(ge=0)] = 0
    estimated_hours: Annotated[int, Field(ge=0, lt=24)] = 0
    start_date: datetime | None = None
    actual_days: Annotated[int, Field(ge=0)] = 0
    actual_hours: Annotated[int, Field(ge=0, lt=24)] = 0
    assigned_to: int | None = None
    assigned_to_username: str | None = None


class TaskSubTaskCreate(TaskSubTaskBase):
    # Server-generated temporary id stored with the sub-task when a creation request is saved.
    temporary_subtask_id: str | None = None
    pass


class TaskApprovedSubTaskOverride(BaseModel):
    temporary_subtask_id: str | None = None
    weightage_priority: Annotated[int, Field(ge=0, le=10)] | None = None
    subtask_priority: SubTaskPriority | None = None


class TaskRequestBase(BaseModel):
    title: str
    description: str
    non_priority_flag: bool = False
    sub_task_count: Annotated[int, Field(ge=0)] | None = None
    department_id: int | None = None
    category_id: int | None = None

    @root_validator(skip_on_failure=True)
    def validate_sub_task_count(cls, values):
        sub_tasks = values.get("sub_tasks")
        sub_task_count = values.get("sub_task_count")

        if sub_task_count is not None and sub_tasks is None:
            raise ValueError("sub_task_count requires sub_tasks payload")

        if sub_task_count is not None and len(sub_tasks) != sub_task_count:
            raise ValueError("sub_task_count must match number of sub_tasks")

        return values


class TaskCreate(TaskRequestBase):
    __payload_version__ = 1

    sub_tasks: list[TaskSubTaskCreate] | None = None


class TaskApprovedPayload(BaseModel):
    non_priority_flag: bool | None = None
    sub_tasks: list[TaskApprovedSubTaskOverride] | None = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    non_priority_flag: bool
    status: TaskStatus
    estimated_days: int
    estimated_hours: int
    start_date: datetime | None = None
    end_date: datetime | None = None
    created_by: UserReference
    department_id: int | None = None
    department: DepartmentReference | None = None
    category: CategoryReference | None = None
    version: str
    parent_task_id: int | None = None

    class Config:
        from_attributes = True


class TaskCreateResponse(TaskResponse):
    sub_tasks: list[SubTaskResponse] = Field(default_factory=list)
    sub_tasks_created_count: int = 0


class TaskWithSubTasksResponse(TaskResponse):
    sub_tasks: list[SubTaskResponse] = Field(default_factory=list)


class TaskAdminResponse(BaseModel):
    id: int
    title: str
    description: str
    non_priority_flag: bool
    status: TaskStatus
    estimated_days: int
    estimated_hours: int
    start_date: datetime | None = None
    end_date: datetime | None = None
    created_by: UserReference
    department_id: int | None = None
    department: DepartmentReference | None = None
    category: CategoryReference | None = None

    class Config:
        from_attributes = True


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
    elapsed_hours: float
    expected_completion_hours: float
    actual_hours: float
    start_date: datetime | None = None
    end_date: datetime | None = None


class TaskTimelineResponse(BaseModel):
    task_id: int
    task_title: str
    start_date: datetime | None = None
    end_date: datetime | None = None
    total_estimated_hours: float
    total_actual_hours: float
    total_expected_hours: float
    bars: list[TimelineBar]
    sub_tasks: list[SubTaskTimelineItem]


class SubTaskPriorityItem(BaseModel):
    sub_task_id: int
    weightage_priority: Annotated[int, Field(ge=0, le=10)]


class TaskPriorityBulkUpdateRequest(BaseModel):
    items: list[SubTaskPriorityItem] = Field(default_factory=list)


class TaskPriorityBulkUpdateResponse(BaseModel):
    task_id: int
    total_priority: int
    items: list[SubTaskPriorityItem]


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    non_priority_flag: bool | None = None
    status: TaskStatus | None = None
    department_id: int | None = None
    category_id: int | None = None


class TaskVersionBumpRequest(BaseModel):
    bump_type: Literal["major", "minor", "patch"] = "patch"


class TaskUpdateRequestDecision(BaseModel):
    comment: str | None = None


class TaskCreationRequestDecision(BaseModel):
    comment: str | None = None
    approved_payload: TaskApprovedPayload | None = None


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


class TaskCreationRequestResponse(BaseModel):
    id: int
    requested_by: UserReference
    status: str
    requested_payload: dict
    review_comment: str | None = None
    reviewed_by: UserReference | None = None
    approved_task_id: int | None = None
    created_at: datetime
    reviewed_at: datetime | None = None


class TaskCreationRequestListResponse(BaseModel):
    items: list[TaskCreationRequestResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
