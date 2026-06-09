from fastapi import APIRouter, Depends
from datetime import datetime
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.security import get_current_user, get_db, require_role
from app.models.sub_task import SubTask
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.dashboard import AdminTaskSummaryResponse, DashboardResponse

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
    # Overdue: tasks with an end_date in the past and not completed
    now = datetime.utcnow()
    overdue_tasks = query.filter(Task.end_date != None).filter(Task.end_date < now).filter(Task.status != TaskStatus.complete.value).count()

    recent_tasks = query.order_by(Task.id.desc()).limit(3).all()

    recent_serialized = [_serialize_recent_task(task) for task in recent_tasks]

    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "pending_tasks": pending_tasks,
        "overdue": overdue_tasks,
        "recent_tasks": recent_serialized,
    }


@router.get("/timeline", response_model=AdminTaskSummaryResponse)
def get_admin_task_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    tasks = (
        db.query(Task)
        .options(selectinload(Task.sub_tasks).selectinload(SubTask.assignee))
        .order_by(Task.id.desc())
        .all()
    )

    items = []
    for task in tasks:
        assignee = next((sub_task.assignee for sub_task in task.sub_tasks if sub_task.assignee), None)
        items.append(
            {
                "id": task.id,
                "title": task.title,
                "start_date": task.start_date,
                "end_date": task.end_date,
                "assignee": _serialize_user_reference(assignee, assignee.id if assignee else None),
                "sub_task_count": len(task.sub_tasks),
            }
        )

    return {"items": items}
