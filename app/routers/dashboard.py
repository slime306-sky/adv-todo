from fastapi import APIRouter, Depends
from datetime import datetime
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_db
from app.models.sub_task import SubTask
from app.models.sub_task import SubTaskStatus
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


def _to_hours(days: int | None, hours: int | None) -> float:
    d = days or 0
    h = hours or 0
    return float((d * 24) + h)


def _build_task_timeline(task: Task, db: Session):
    sub_tasks = db.query(SubTask).filter(SubTask.task_id == task.id).all()

    total_estimated_hours = sum(_to_hours(st.estimated_days, st.estimated_hours) for st in sub_tasks)
    total_actual_hours = sum(_to_hours(st.actual_days, st.actual_hours) for st in sub_tasks)

    sub_task_count = len(sub_tasks)
    total_priority = sum(st.weightage_priority for st in sub_tasks)

    sub_tasks_timeline = []
    total_expected_hours = 0.0

    for st in sub_tasks:
        if sub_task_count == 0:
            weight = 0.0
        elif total_priority > 0:
            weight = st.weightage_priority / total_priority
        else:
            weight = 1.0 / sub_task_count

        expected_hours = (
            round(total_estimated_hours * weight, 2)
            if st.status == SubTaskStatus.complete.value
            else 0.0
        )
        total_expected_hours += expected_hours

        sub_tasks_timeline.append(
            {
                "sub_task_id": st.id,
                "title": st.title,
                "status": st.status,
                "priority": st.weightage_priority,
                "estimated_hours": round(_to_hours(st.estimated_days, st.estimated_hours), 2),
                "actual_hours": round(_to_hours(st.actual_days, st.actual_hours), 2),
                "expected_hours": expected_hours,
                "start_date": st.start_date,
                "end_date": st.end_date,
            }
        )

    if total_estimated_hours > 0:
        estimated_percentage = 100.0
        actual_percentage = round((total_actual_hours / total_estimated_hours) * 100, 2)
        expected_percentage = round((total_expected_hours / total_estimated_hours) * 100, 2)
    else:
        estimated_percentage = 0.0
        actual_percentage = 0.0
        expected_percentage = 0.0

    return {
        "task_id": task.id,
        "task_title": task.title,
        "total_estimated_hours": round(total_estimated_hours, 2),
        "total_actual_hours": round(total_actual_hours, 2),
        "total_expected_hours": round(total_expected_hours, 2),
        "bars": [
            {"key": "estimated", "label": "How much time it will take", "hours": round(total_estimated_hours, 2), "percentage": estimated_percentage},
            {"key": "actual", "label": "How much time user took", "hours": round(total_actual_hours, 2), "percentage": actual_percentage},
            {"key": "expected", "label": "How much time it should have taken", "hours": round(total_expected_hours, 2), "percentage": expected_percentage},
        ],
        "sub_tasks": sub_tasks_timeline,
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
    for idx, task in enumerate(recent_tasks):
        recent_serialized[idx]["timeline"] = _build_task_timeline(task, db)

    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "pending_tasks": pending_tasks,
        "overdue": overdue_tasks,
        "recent_tasks": recent_serialized,
    }
