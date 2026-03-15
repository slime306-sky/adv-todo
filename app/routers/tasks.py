from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db, require_role
from app.models.sub_task import SubTask
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.task import (
    TaskAdminListResponse,
    TaskAdminResponse,
    TaskCreate,
    TaskListResponse,
    TaskProgressResponse,
    TaskResponse,
    TaskUpdate,
)

router = APIRouter(tags=["tasks"])


@router.post("/tasks", response_model=TaskResponse)
def create_task(
    task: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "admin":
        if task.assigned_to_username:
            assigned_user = db.query(User).filter(User.username == task.assigned_to_username).first()
        elif task.assigned_to is not None:
            assigned_user = db.query(User).filter(User.id == task.assigned_to).first()
        else:
            assigned_user = None

        if not assigned_user:
            raise api_error(
                status_code=404,
                code="ASSIGNED_USER_NOT_FOUND",
                message="Assigned user not found",
            )
    else:
        assigned_user = current_user

    new_task = Task(
        title=task.title,
        description=task.description,
        start_date=task.start_date,
        end_date=task.end_date,
        created_by=current_user.id,
        assigned_to=assigned_user.id,
    )

    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    log_audit_event(
        db=db,
        action="CREATE",
        entity_type="task",
        entity_id=new_task.id,
        user_id=current_user.id,
        message="Task created",
        details={"title": new_task.title, "assigned_to": new_task.assigned_to},
    )
    db.commit()
    return new_task


@router.get("/my-tasks", response_model=TaskListResponse)
def get_my_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    query = db.query(Task).filter(Task.assigned_to == current_user.id)

    if status:
        query = query.filter(Task.status == status)

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(Task.title.ilike(search_pattern), Task.description.ilike(search_pattern))
        )

    total = query.count()
    items = (
        query.order_by(Task.id.desc())
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


@router.put("/tasks/{task_id}/complete")
def complete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    if task.assigned_to != current_user.id:
        raise api_error(
            status_code=403,
            code="FORBIDDEN_TASK_ACCESS",
            message="Not authorized",
        )

    task.status = TaskStatus.complete.value
    log_audit_event(
        db=db,
        action="COMPLETE",
        entity_type="task",
        entity_id=task.id,
        user_id=current_user.id,
        message="Task marked complete",
    )
    db.commit()

    return {"message": "Task marked complete"}


@router.get("/tasks", response_model=TaskAdminListResponse)
def get_all_tasks_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    assigned_to: int | None = Query(default=None),
):
    query = db.query(Task)

    if status:
        query = query.filter(Task.status == status)

    if assigned_to is not None:
        query = query.filter(Task.assigned_to == assigned_to)

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(Task.title.ilike(search_pattern), Task.description.ilike(search_pattern))
        )

    total = query.count()
    tasks = (
        query.order_by(Task.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
    for task in tasks:
        result.append(
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "estimated_days": task.estimated_days,
                "estimated_hours": task.estimated_hours,
                "creator_username": task.creator.username,
                "assignee_username": task.assignee.username,
            }
        )

    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/tasks/{task_id}/progress", response_model=TaskProgressResponse)
def get_task_progress(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    if task.assigned_to != current_user.id and current_user.role != "admin":
        raise api_error(
            status_code=403,
            code="FORBIDDEN_TASK_ACCESS",
            message="Not authorized",
        )

    total_subtasks = (
        db.query(func.count(SubTask.id)).filter(SubTask.task_id == task_id).scalar() or 0
    )
    completed_subtasks = (
        db.query(func.count(SubTask.id))
        .filter(SubTask.task_id == task_id)
        .filter(SubTask.status == TaskStatus.complete.value)
        .scalar()
        or 0
    )

    progress_percentage = (
        round((completed_subtasks / total_subtasks) * 100, 2)
        if total_subtasks > 0
        else 0.0
    )

    return {
        "task_id": task_id,
        "total_subtasks": total_subtasks,
        "completed_subtasks": completed_subtasks,
        "progress_percentage": progress_percentage,
        "is_completed": total_subtasks > 0 and completed_subtasks == total_subtasks,
    }


@router.put("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    task_update: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    update_data = task_update.dict(exclude_unset=True)
    update_data.pop("assigned_to_username", None)

    if "status" in update_data and task.status == TaskStatus.complete.value:
        raise api_error(
            status_code=400,
            code="TASK_ALREADY_COMPLETE",
            message="A completed task cannot be reopened",
        )

    if "assigned_to_username" in task_update.dict(exclude_unset=True):
        user = db.query(User).filter(User.username == task_update.assigned_to_username).first()
        if not user:
            raise api_error(
                status_code=404,
                code="ASSIGNED_USER_NOT_FOUND",
                message="Assigned user not found",
            )
        update_data["assigned_to"] = user.id
    elif "assigned_to" in update_data:
        user = db.query(User).filter(User.id == update_data["assigned_to"]).first()
        if not user:
            raise api_error(
                status_code=404,
                code="ASSIGNED_USER_NOT_FOUND",
                message="Assigned user not found",
            )

    for key, value in update_data.items():
        setattr(task, key, value)

    log_audit_event(
        db=db,
        action="UPDATE",
        entity_type="task",
        entity_id=task.id,
        user_id=current_user.id,
        message="Task updated",
        details={"updated_fields": list(update_data.keys())},
    )
    db.commit()
    db.refresh(task)

    return task


@router.post("/tasks/{task_id}/revise", response_model=TaskResponse)
def revise_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    if task.status != TaskStatus.complete.value:
        raise api_error(
            status_code=400,
            code="TASK_NOT_COMPLETE",
            message="Only completed tasks can be revised",
        )

    if task.assigned_to != current_user.id and current_user.role != "admin":
        raise api_error(
            status_code=403,
            code="FORBIDDEN_TASK_ACCESS",
            message="Not authorized",
        )

    new_version = Task(
        title=task.title,
        description=task.description,
        start_date=task.start_date,
        end_date=task.end_date,
        status=TaskStatus.not_complete.value,
        estimated_days=0,
        estimated_hours=0,
        created_by=current_user.id,
        assigned_to=task.assigned_to,
        version=task.version + 1,
        parent_task_id=task.id,
    )

    db.add(new_version)
    db.commit()
    db.refresh(new_version)

    log_audit_event(
        db=db,
        action="REVISE",
        entity_type="task",
        entity_id=new_version.id,
        user_id=current_user.id,
        message="New task version created",
        details={"previous_task_id": task.id, "new_version": new_version.version},
    )
    db.commit()

    return new_version


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    log_audit_event(
        db=db,
        action="DELETE",
        entity_type="task",
        entity_id=task.id,
        user_id=current_user.id,
        message="Task deleted",
        details={"title": task.title},
    )
    db.delete(task)
    db.commit()

    return {"message": "Task deleted successfully"}
