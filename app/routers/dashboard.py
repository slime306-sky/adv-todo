from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_db
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.dashboard import DashboardResponse

router = APIRouter(tags=["dashboard"])


def _serialize_user_reference(user: User | None, fallback_id: int | None):
    if user:
        return {"id": user.id, "name": user.username}
    return {"id": fallback_id, "name": "Unknown"}


def _serialize_recent_task(task: Task):
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "end_date": task.end_date,
        "assigned_to": _serialize_user_reference(task.assignee, task.assigned_to),
    }


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Task)
    if current_user.role != "admin":
        query = query.filter(Task.assigned_to == current_user.id)

    total_tasks = query.count()
    completed_tasks = query.filter(Task.status == TaskStatus.complete.value).count()
    in_progress_tasks = query.filter(Task.status == TaskStatus.in_progress.value).count()
    overdue_tasks = query.filter(
        and_(
            Task.end_date < datetime.utcnow(),
            Task.status != TaskStatus.complete.value,
        )
    ).count()

    recent_tasks = query.order_by(Task.id.desc()).limit(3).all()

    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "overdue_tasks": overdue_tasks,
        "recent_tasks": [_serialize_recent_task(task) for task in recent_tasks],
    }
