from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db
from app.models.sub_task import SubTask
from app.models.task import Task
from app.models.user import User
from app.schemas.sub_task import (
    SubTaskCreate,
    SubTaskListResponse,
    SubTaskResponse,
    SubTaskUpdate,
)

router = APIRouter(tags=["sub-tasks"])


def recalculate_task_estimated_time(db: Session, task_id: int):
    total_hours = (
        db.query(
            func.coalesce(
                func.sum((SubTask.estimated_days * 24) + SubTask.estimated_hours), 0
            )
        )
        .filter(SubTask.task_id == task_id)
        .scalar()
    )

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    task.estimated_days = total_hours // 24
    task.estimated_hours = total_hours % 24


def ensure_user_can_manage_task(task: Task, user: User):
    if user.role != "admin" and task.assigned_to != user.id:
        raise api_error(
            status_code=403,
            code="FORBIDDEN_TASK_ACCESS",
            message="Not authorized",
        )


def validate_task(db: Session, task_id: int):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")
    return task


@router.post("/subtasks", response_model=SubTaskResponse)
def create_sub_task(
    sub_task: SubTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = validate_task(db, sub_task.task_id)
    ensure_user_can_manage_task(task, current_user)

    new_sub_task = SubTask(
        title=sub_task.title,
        description=sub_task.description,
        status=sub_task.status.value,
        estimated_days=sub_task.estimated_days,
        estimated_hours=sub_task.estimated_hours,
        task_id=sub_task.task_id,
        created_by=current_user.id,
    )

    db.add(new_sub_task)
    recalculate_task_estimated_time(db, sub_task.task_id)
    db.commit()
    db.refresh(new_sub_task)
    log_audit_event(
        db=db,
        action="CREATE",
        entity_type="sub_task",
        entity_id=new_sub_task.id,
        user_id=current_user.id,
        message="Sub task created",
        details={"task_id": new_sub_task.task_id, "title": new_sub_task.title},
    )
    db.commit()
    return new_sub_task


@router.get("/subtasks", response_model=SubTaskListResponse)
def get_sub_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    task_id: int | None = Query(default=None),
):
    query = db.query(SubTask)

    if current_user.role == "admin":
        pass
    else:
        query = query.join(Task, Task.id == SubTask.task_id).filter(
            Task.assigned_to == current_user.id
        )

    if task_id is not None:
        query = query.filter(SubTask.task_id == task_id)

    if status:
        query = query.filter(SubTask.status == status)

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                SubTask.title.ilike(search_pattern),
                SubTask.description.ilike(search_pattern),
            )
        )

    total = query.count()
    items = (
        query.order_by(SubTask.id.desc())
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


@router.get("/subtasks/{sub_task_id}", response_model=SubTaskResponse)
def get_sub_task_by_id(
    sub_task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise api_error(
            status_code=404,
            code="SUBTASK_NOT_FOUND",
            message="Sub task not found",
        )

    task = db.query(Task).filter(Task.id == sub_task.task_id).first()
    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    ensure_user_can_manage_task(task, current_user)
    return sub_task


@router.put("/subtasks/{sub_task_id}", response_model=SubTaskResponse)
def update_sub_task(
    sub_task_id: int,
    sub_task_update: SubTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise api_error(
            status_code=404,
            code="SUBTASK_NOT_FOUND",
            message="Sub task not found",
        )

    existing_task = db.query(Task).filter(Task.id == sub_task.task_id).first()
    if not existing_task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")
    ensure_user_can_manage_task(existing_task, current_user)

    update_data = sub_task_update.dict(exclude_unset=True)

    if "status" in update_data and sub_task.status == "complete":
        raise api_error(
            status_code=400,
            code="SUBTASK_ALREADY_COMPLETE",
            message="A completed sub-task cannot be reopened",
        )

    new_task_id = update_data.get("task_id", sub_task.task_id)

    validate_task(db, new_task_id)

    if "status" in update_data and update_data["status"] is not None:
        update_data["status"] = update_data["status"].value

    old_task_id = sub_task.task_id

    for key, value in update_data.items():
        setattr(sub_task, key, value)

    recalculate_task_estimated_time(db, old_task_id)
    if sub_task.task_id != old_task_id:
        recalculate_task_estimated_time(db, sub_task.task_id)

    log_audit_event(
        db=db,
        action="UPDATE",
        entity_type="sub_task",
        entity_id=sub_task.id,
        user_id=current_user.id,
        message="Sub task updated",
        details={"updated_fields": list(update_data.keys())},
    )
    db.commit()
    db.refresh(sub_task)
    return sub_task


@router.delete("/subtasks/{sub_task_id}")
def delete_sub_task(
    sub_task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise api_error(
            status_code=404,
            code="SUBTASK_NOT_FOUND",
            message="Sub task not found",
        )

    task = db.query(Task).filter(Task.id == sub_task.task_id).first()
    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")
    ensure_user_can_manage_task(task, current_user)

    task_id = sub_task.task_id
    log_audit_event(
        db=db,
        action="DELETE",
        entity_type="sub_task",
        entity_id=sub_task.id,
        user_id=current_user.id,
        message="Sub task deleted",
        details={"task_id": sub_task.task_id, "title": sub_task.title},
    )
    db.delete(sub_task)
    recalculate_task_estimated_time(db, task_id)
    db.commit()

    return {"message": "Sub task deleted successfully"}
