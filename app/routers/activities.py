from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db, require_role
from app.models.activity import Activity
from app.models.sub_task import SubTask
from app.models.task import Task
from app.models.user import User
from app.schemas.activity import (
    ActivityCreate,
    ActivityListResponse,
    ActivityResponse,
    ActivityUpdate,
)

router = APIRouter(tags=["activities"])


@router.post("/activities", response_model=ActivityResponse)
def create_activity(
    activity: ActivityCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    sub_task = db.query(SubTask).filter(SubTask.id == activity.sub_task_id).first()
    if not sub_task:
        raise api_error(
            status_code=404,
            code="SUBTASK_NOT_FOUND",
            message="Sub task not found",
        )

    new_activity = Activity(
        title=activity.title,
        description=activity.description,
        date=activity.date,
        sub_task_id=activity.sub_task_id,
        created_by=admin.id,
    )

    db.add(new_activity)
    db.commit()
    db.refresh(new_activity)
    log_audit_event(
        db=db,
        action="CREATE",
        entity_type="activity",
        entity_id=new_activity.id,
        user_id=admin.id,
        message="Activity created",
        details={"sub_task_id": new_activity.sub_task_id, "title": new_activity.title},
    )
    db.commit()
    return new_activity


@router.put("/activities/{activity_id}", response_model=ActivityResponse)
def update_activity(
    activity_id: int,
    activity_update: ActivityUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise api_error(
            status_code=404,
            code="ACTIVITY_NOT_FOUND",
            message="Activity not found",
        )

    update_data = activity_update.dict(exclude_unset=True)

    if "status" in update_data and activity.status == "complete":
        raise api_error(
            status_code=400,
            code="ACTIVITY_ALREADY_COMPLETE",
            message="A completed activity cannot be reopened",
        )

    if "status" in update_data and update_data["status"] not in [
        "complete",
        "not complete",
    ]:
        raise api_error(
            status_code=400,
            code="INVALID_ACTIVITY_STATUS",
            message="Invalid status",
        )

    if "sub_task_id" in update_data:
        sub_task = db.query(SubTask).filter(SubTask.id == update_data["sub_task_id"]).first()
        if not sub_task:
            raise api_error(
                status_code=404,
                code="SUBTASK_NOT_FOUND",
                message="Sub task not found",
            )

    for key, value in update_data.items():
        setattr(activity, key, value)

    log_audit_event(
        db=db,
        action="UPDATE",
        entity_type="activity",
        entity_id=activity.id,
        user_id=admin.id,
        message="Activity updated",
        details={"updated_fields": list(update_data.keys())},
    )
    db.commit()
    db.refresh(activity)
    return activity


@router.delete("/activities/{activity_id}")
def delete_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise api_error(
            status_code=404,
            code="ACTIVITY_NOT_FOUND",
            message="Activity not found",
        )

    log_audit_event(
        db=db,
        action="DELETE",
        entity_type="activity",
        entity_id=activity.id,
        user_id=admin.id,
        message="Activity deleted",
        details={"title": activity.title},
    )
    db.delete(activity)
    db.commit()
    db.refresh(activity)
    return {"message": "Activity deleted successfully"}


@router.get("/tasks/{task_id}/activities", response_model=ActivityListResponse)
def get_task_activities(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sub_task_id: int | None = Query(default=None),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    if task.assigned_to != user.id and user.role != "admin":
        raise api_error(
            status_code=403,
            code="FORBIDDEN_TASK_ACCESS",
            message="Not authorized",
        )

    query = (
        db.query(Activity)
        .join(SubTask, SubTask.id == Activity.sub_task_id)
        .filter(SubTask.task_id == task_id)
    )

    if sub_task_id is not None:
        query = query.filter(Activity.sub_task_id == sub_task_id)

    if status:
        query = query.filter(Activity.status == status)

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Activity.title.ilike(search_pattern),
                Activity.description.ilike(search_pattern),
            )
        )

    total = query.count()
    items = (
        query.order_by(Activity.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }
