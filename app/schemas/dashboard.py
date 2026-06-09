from pydantic import BaseModel

from app.models.task import TaskStatus
from app.schemas.user import UserReference
from app.schemas.task import TaskTimelineResponse


class DashboardRecentTask(BaseModel):
    id: int
    title: str
    status: TaskStatus
    created_by: UserReference
    timeline: TaskTimelineResponse | None = None

    class Config:
        from_attributes = True


class DashboardResponse(BaseModel):
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    overdue: int
    recent_tasks: list[DashboardRecentTask]
