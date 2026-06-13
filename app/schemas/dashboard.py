from datetime import datetime

from pydantic import BaseModel

from app.models.task import TaskStatus
from app.schemas.user import UserReference


class DashboardRecentTask(BaseModel):
    id: int
    title: str
    status: TaskStatus
    created_by: UserReference

    class Config:
        from_attributes = True


class DashboardResponse(BaseModel):
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    overdue: int
    recent_tasks: list[DashboardRecentTask]


class AdminTaskSummaryItem(BaseModel):
    id: int
    title: str
    start_date: datetime | None = None
    end_date: datetime | None = None
    assignee: UserReference | None = None
    sub_task_count: int
    total_estimated_hours: float = 0.0
    total_actual_hours: float = 0.0
    total_elapsed_hours: float = 0.0
    total_expected_completion_hours: float = 0.0


class AdminTaskSummaryResponse(BaseModel):
    items: list[AdminTaskSummaryItem]
