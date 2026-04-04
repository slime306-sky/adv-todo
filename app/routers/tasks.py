from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db, require_role
from app.models.sub_task import SubTask
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.routers.sub_tasks import (
    ensure_user_can_manage_task,
    get_task_priority_total,
    recalculate_task_estimated_time,
    sync_task_completion_status,
    validate_priority_total,
)
from app.schemas.task import (
    TaskPriorityBulkUpdateRequest,
    TaskPriorityBulkUpdateResponse,
    TaskAdminListResponse,
    TaskAdminResponse,
    TaskCreate,
    TaskCreateResponse,
    TaskListResponse,
    TaskProgressResponse,
    TaskResponse,
    TaskTimelineResponse,
    TaskWithSubTasksResponse,
    TaskUpdate,
)

router = APIRouter(tags=["tasks"])


def _serialize_user_reference(user: User | None, fallback_id: int | None):
    if user:
        return {"id": user.id, "name": user.username}
    if fallback_id is not None:
        return {"id": fallback_id, "name": "Unknown"}
    return None


def _serialize_sub_task(sub_task: SubTask):
    return {
        "id": sub_task.id,
        "title": sub_task.title,
        "description": sub_task.description,
        "status": sub_task.status,
        "priority": sub_task.priority,
        "estimated_days": sub_task.estimated_days,
        "estimated_hours": sub_task.estimated_hours,
        "actual_days": sub_task.actual_days,
        "actual_hours": sub_task.actual_hours,
        "created_at": sub_task.created_at,
        "completed_at": sub_task.completed_at,
        "task_id": sub_task.task_id,
        "created_by": _serialize_user_reference(sub_task.creator, sub_task.created_by),
    }


def _to_hours(days: int, hours: int) -> float:
    return float((days * 24) + hours)


def _serialize_task(task: Task, include_sub_tasks: bool = False):
    payload = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "start_date": task.start_date,
        "end_date": task.end_date,
        "status": task.status,
        "estimated_days": task.estimated_days,
        "estimated_hours": task.estimated_hours,
        "created_by": _serialize_user_reference(task.creator, task.created_by),
        "assigned_to": _serialize_user_reference(task.assignee, task.assigned_to),
        "version": task.version,
        "parent_task_id": task.parent_task_id,
    }

    if include_sub_tasks:
        payload["sub_tasks"] = [_serialize_sub_task(sub_task) for sub_task in task.sub_tasks]

    return payload


@router.post("/tasks", response_model=TaskCreateResponse)
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
    created_sub_tasks: list[SubTask] = []
    try:
        db.flush()

        if task.sub_tasks:
            validate_priority_total(sum(sub_task.priority for sub_task in task.sub_tasks))

            for sub_task in task.sub_tasks:
                new_sub_task = SubTask(
                    title=sub_task.title,
                    description=sub_task.description,
                    status=sub_task.status.value,
                    priority=sub_task.priority,
                    estimated_days=sub_task.estimated_days,
                    estimated_hours=sub_task.estimated_hours,
                    actual_days=sub_task.actual_days,
                    actual_hours=sub_task.actual_hours,
                    task_id=new_task.id,
                    created_by=current_user.id,
                )
                db.add(new_sub_task)
                created_sub_tasks.append(new_sub_task)

            recalculate_task_estimated_time(db, new_task.id)
            sync_task_completion_status(db, new_task.id)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise api_error(
            status_code=500,
            code="TRANSACTION_FAILED",
            message="Failed to create task with subtasks",
            dev_message=str(exc),
        )

    db.refresh(new_task)
    for sub_task in created_sub_tasks:
        db.refresh(sub_task)

    log_audit_event(
        db=db,
        action="CREATE",
        entity_type="task",
        entity_id=new_task.id,
        user_id=current_user.id,
        message="Task created",
        details={
            "title": new_task.title,
            "assigned_to": new_task.assigned_to,
            "sub_tasks_count": len(created_sub_tasks),
        },
    )
    db.commit()
    return {
        **_serialize_task(new_task, include_sub_tasks=True),
        "sub_tasks": [_serialize_sub_task(sub_task) for sub_task in created_sub_tasks],
        "sub_tasks_created_count": len(created_sub_tasks),
    }


@router.get("/my-tasks", response_model=TaskListResponse)
def get_my_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    query = db.query(Task).options(selectinload(Task.sub_tasks)).filter(Task.assigned_to == current_user.id)

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

    serialized_items = [_serialize_task(task, include_sub_tasks=True) for task in items]

    return {
        "items": serialized_items,
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
                "start_date": task.start_date,
                "end_date": task.end_date,
                "status": task.status,
                "estimated_days": task.estimated_days,
                "estimated_hours": task.estimated_hours,
                "created_by": _serialize_user_reference(task.creator, task.created_by),
                "assigned_to": _serialize_user_reference(task.assignee, task.assigned_to),
            }
        )

    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/tasks/{task_id}", response_model=TaskWithSubTasksResponse)
def get_task_by_id(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = (
        db.query(Task)
        .options(selectinload(Task.sub_tasks))
        .filter(Task.id == task_id)
        .first()
    )

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    if task.assigned_to != current_user.id and current_user.role != "admin":
        raise api_error(
            status_code=403,
            code="FORBIDDEN_TASK_ACCESS",
            message="Not authorized",
        )

    return _serialize_task(task, include_sub_tasks=True)


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


@router.get("/tasks/{task_id}/timeline", response_model=TaskTimelineResponse)
def get_task_timeline(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = (
        db.query(Task)
        .options(selectinload(Task.sub_tasks))
        .filter(Task.id == task_id)
        .first()
    )

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    if task.assigned_to != current_user.id and current_user.role != "admin":
        raise api_error(
            status_code=403,
            code="FORBIDDEN_TASK_ACCESS",
            message="Not authorized",
        )

    total_estimated_hours = sum(
        _to_hours(sub_task.estimated_days, sub_task.estimated_hours)
        for sub_task in task.sub_tasks
    )
    total_actual_hours = sum(
        _to_hours(sub_task.actual_days, sub_task.actual_hours) for sub_task in task.sub_tasks
    )

    sub_task_count = len(task.sub_tasks)
    total_priority = sum(sub_task.priority for sub_task in task.sub_tasks)

    sub_tasks_timeline = []
    total_expected_hours = 0.0

    for sub_task in task.sub_tasks:
        if sub_task_count == 0:
            weight = 0.0
        elif total_priority > 0:
            weight = sub_task.priority / total_priority
        else:
            weight = 1.0 / sub_task_count

        expected_hours = (
            round(total_estimated_hours * weight, 2)
            if sub_task.status == TaskStatus.complete.value
            else 0.0
        )
        total_expected_hours += expected_hours

        sub_tasks_timeline.append(
            {
                "sub_task_id": sub_task.id,
                "title": sub_task.title,
                "status": sub_task.status,
                "priority": sub_task.priority,
                "estimated_hours": round(
                    _to_hours(sub_task.estimated_days, sub_task.estimated_hours), 2
                ),
                "actual_hours": round(
                    _to_hours(sub_task.actual_days, sub_task.actual_hours), 2
                ),
                "expected_hours": expected_hours,
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
            {
                "key": "estimated",
                "label": "How much time it will take",
                "hours": round(total_estimated_hours, 2),
                "percentage": estimated_percentage,
            },
            {
                "key": "actual",
                "label": "How much time user took",
                "hours": round(total_actual_hours, 2),
                "percentage": actual_percentage,
            },
            {
                "key": "expected",
                "label": "How much time it should have taken",
                "hours": round(total_expected_hours, 2),
                "percentage": expected_percentage,
            },
        ],
        "sub_tasks": sub_tasks_timeline,
    }


@router.put(
    "/tasks/{task_id}/subtasks/priorities",
    response_model=TaskPriorityBulkUpdateResponse,
)
@router.post(
    "/tasks/{task_id}/subtasks/priorities",
    response_model=TaskPriorityBulkUpdateResponse,
)
def update_task_sub_task_priorities(
    task_id: int,
    payload: TaskPriorityBulkUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = (
        db.query(Task)
        .options(selectinload(Task.sub_tasks))
        .filter(Task.id == task_id)
        .first()
    )
    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    ensure_user_can_manage_task(task, current_user)

    if not task.sub_tasks:
        raise api_error(
            status_code=400,
            code="SUBTASKS_NOT_FOUND",
            message="Task has no sub-tasks to reprioritize",
        )

    if not payload.items:
        raise api_error(
            status_code=400,
            code="EMPTY_PRIORITY_PAYLOAD",
            message="Provide all sub-task priorities in items",
        )

    if len(payload.items) != len(task.sub_tasks):
        raise api_error(
            status_code=400,
            code="INCOMPLETE_PRIORITY_PAYLOAD",
            message="Payload must include every sub-task exactly once",
        )

    payload_ids = [item.sub_task_id for item in payload.items]
    if len(set(payload_ids)) != len(payload_ids):
        raise api_error(
            status_code=400,
            code="DUPLICATE_SUBTASK_IN_PAYLOAD",
            message="Each sub-task id must appear only once",
        )

    existing_ids = {sub_task.id for sub_task in task.sub_tasks}
    if set(payload_ids) != existing_ids:
        raise api_error(
            status_code=400,
            code="INVALID_SUBTASK_SET",
            message="Payload sub-task ids must exactly match this task's sub-tasks",
        )

    total_priority = sum(item.priority for item in payload.items)
    validate_priority_total(total_priority)

    priority_map = {item.sub_task_id: item.priority for item in payload.items}
    for sub_task in task.sub_tasks:
        sub_task.priority = priority_map[sub_task.id]

    db.flush()
    validate_priority_total(get_task_priority_total(db, task_id))

    log_audit_event(
        db=db,
        action="UPDATE",
        entity_type="task",
        entity_id=task.id,
        user_id=current_user.id,
        message="Sub-task priorities updated in bulk",
        details={"sub_task_count": len(payload.items), "total_priority": total_priority},
    )
    db.commit()

    return {
        "task_id": task.id,
        "total_priority": total_priority,
        "items": payload.items,
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

    return _serialize_task(task)


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

    return _serialize_task(new_version)


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
