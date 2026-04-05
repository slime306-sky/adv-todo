from pydantic import BaseModel

from app.models.task import TaskStatus
from app.schemas.user import UserReference


class DashboardRecentTask(BaseModel):
    id: int
    title: str
    status: TaskStatus
    created_by: UserReference

    class Config:
        orm_mode = True


class DashboardResponse(BaseModel):
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    recent_tasks: list[DashboardRecentTask]
