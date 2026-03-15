from datetime import datetime

from pydantic import BaseModel

from app.models.task import TaskStatus


class DashboardRecentTask(BaseModel):
    id: int
    title: str
    status: TaskStatus
    end_date: datetime | None = None
    assigned_to: int

    class Config:
        orm_mode = True


class DashboardResponse(BaseModel):
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    overdue_tasks: int
    recent_tasks: list[DashboardRecentTask]
