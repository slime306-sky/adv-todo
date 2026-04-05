from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_db
from app.models.sub_task import SubTask
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.dashboard import DashboardResponse

router = APIRouter(tags=["dashboard"])


def _serialize_user_reference(user: User | None, fallback_id: int | None):
    if not user and fallback_id is None:
        return None

    return {
        "id": user.id if user else fallback_id,
        "name": user.username if user else "Unknown",
    }


def _serialize_recent_task(task: Task):
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "created_by": _serialize_user_reference(task.creator, task.created_by),
    }


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Task)
    if current_user.role != "admin":
        query = query.filter(
            or_(
                Task.created_by == current_user.id,
                Task.id.in_(db.query(SubTask.task_id).filter(SubTask.assigned_to == current_user.id)),
            )
        )

    total_tasks = query.count()
    completed_tasks = query.filter(Task.status == TaskStatus.complete.value).count()
    in_progress_tasks = query.filter(Task.status == TaskStatus.in_progress.value).count()
    pending_tasks = query.filter(Task.status == TaskStatus.not_complete.value).count()

    recent_tasks = query.order_by(Task.id.desc()).limit(3).all()

    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "pending_tasks": pending_tasks,
        "recent_tasks": [_serialize_recent_task(task) for task in recent_tasks],
    }
