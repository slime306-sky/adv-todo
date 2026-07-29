from fastapi import APIRouter, Depends, Query
from datetime import datetime, timedelta, timezone
from math import floor
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db, require_role
from app.core.timeline import build_sub_task_timing_fields
from app.models.sub_task import SubTask, SubTaskPriority, SubTaskStatus
from app.models.sub_task_update_request import SubTaskUpdateRequest, SubTaskUpdateRequestStatus
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.sub_task import (
    SubTaskCreate,
    SubTaskListResponse,
    SubTaskResponse,
    SubTaskUpdateRequestDecision,
    SubTaskUpdateRequestListResponse,
    SubTaskUpdateRequestResponse,
    SubTaskUpdate,
)

router = APIRouter(tags=["sub-tasks"])
PRIORITY_TOTAL_TARGET = 100


def _normalize_weightage_priority_values(weightage_priorities: list[int | None]) -> list[int]:
    if not weightage_priorities:
        return []

    sanitized = [max(0, int(value or 0)) for value in weightage_priorities]
    total = sum(sanitized)

    if total <= 0:
        base = [PRIORITY_TOTAL_TARGET // len(sanitized)] * len(sanitized)
        for index in range(PRIORITY_TOTAL_TARGET - sum(base)):
            base[index] += 1
        return base

    scaled = [value * PRIORITY_TOTAL_TARGET / total for value in sanitized]
    base = [int(floor(value)) for value in scaled]
    remainder = PRIORITY_TOTAL_TARGET - sum(base)
    fractional_parts = sorted(
        ((scaled[index] - base[index], index) for index in range(len(sanitized))),
        key=lambda item: (-item[0], item[1]),
    )

    for _, index in fractional_parts[:remainder]:
        base[index] += 1

    return base


def _rebalance_task_weightage_priorities(db: Session, task_id: int):
    task_sub_tasks = (
        db.query(SubTask)
        .filter(SubTask.task_id == task_id)
        .order_by(SubTask.id.asc())
        .all()
    )

    if not task_sub_tasks:
        return

    normalized_priorities = _normalize_weightage_priority_values(
        [sub_task.weightage_priority for sub_task in task_sub_tasks]
    )

    for sub_task, normalized_priority in zip(task_sub_tasks, normalized_priorities):
        sub_task.weightage_priority = normalized_priority


def _serialize_user_reference(user: User | None, fallback_id: int | None):
    if user:
        return {"id": user.id, "name": user.username}
    if fallback_id is not None:
        return {"id": fallback_id, "name": "Unknown"}
    return None


def _serialize_sub_task(sub_task: SubTask):
    end_date = sub_task.calculate_end_date() if sub_task.start_date else None
    return {
        "id": sub_task.id,
        "title": sub_task.title,
        "description": sub_task.description,
        "status": sub_task.status,
        "weightage_priority": sub_task.weightage_priority,
        "subtask_priority": sub_task.subtask_priority,
        "estimated_days": sub_task.estimated_days,
        "estimated_hours": sub_task.estimated_hours,
        "start_date": sub_task.start_date,
        "end_date": end_date,
        "actual_days": sub_task.actual_days,
        "actual_hours": sub_task.actual_hours,
        **build_sub_task_timing_fields(sub_task),
        "created_at": sub_task.created_at,
        "completed_at": sub_task.completed_at,
        "task_id": sub_task.task_id,
        "created_by": _serialize_user_reference(sub_task.creator, sub_task.created_by),
        "assigned_to": _serialize_user_reference(sub_task.assignee, sub_task.assigned_to),
    }


def resolve_assigned_user(
    db: Session,
    assigned_to: int | None,
    assigned_to_username: str | None,
    current_user: User,
):
    if current_user.role != "admin":
        return current_user

    if assigned_to_username:
        user = db.query(User).filter(User.username == assigned_to_username).first()
    elif assigned_to is not None:
        user = db.query(User).filter(User.id == assigned_to).first()
    else:
        raise api_error(
            status_code=400,
            code="ASSIGNEE_REQUIRED_FOR_ADMIN",
            message="Admin must assign the task to a non-admin user",
        )

    if not user:
        raise api_error(
            status_code=404,
            code="ASSIGNED_USER_NOT_FOUND",
            message="Assigned user not found",
        )

    if user.role == "admin":
        raise api_error(
            status_code=400,
            code="ADMIN_CANNOT_BE_ASSIGNED",
            message="Admin users cannot be assigned tasks or sub-tasks",
        )

    return user


def _serialize_sub_task_update_request(request: SubTaskUpdateRequest):
    return {
        "id": request.id,
        "sub_task_id": request.sub_task_id,
        "requested_by": _serialize_user_reference(request.requester, request.requested_by),
        "status": request.status,
        "requested_changes": request.requested_changes,
        "review_comment": request.review_comment,
        "reviewed_by": _serialize_user_reference(request.reviewer, request.reviewed_by),
        "created_at": request.created_at,
        "reviewed_at": request.reviewed_at,
    }


def _auto_fill_actual_time_on_completion(sub_task: SubTask):
    if not sub_task.created_at or not sub_task.completed_at:
        return

    duration_seconds = max(
        0.0, (sub_task.completed_at - sub_task.created_at).total_seconds()
    )
    total_hours = int(floor(duration_seconds / 3600))
    sub_task.actual_days = total_hours // 24
    sub_task.actual_hours = total_hours % 24


def recalculate_task_estimated_time(db: Session, task_id: int):
    # Session uses autoflush=False, so flush pending inserts/updates/deletes
    # to make aggregate totals reflect the latest sub-task changes.
    db.flush()

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

    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    sub_tasks = db.query(SubTask).filter(SubTask.task_id == task_id).all()
    start_candidates = [_normalize_datetime(sub_task.start_date) for sub_task in sub_tasks if sub_task.start_date]

    if not start_candidates:
        task.start_date = None
        task.end_date = None
        return

    task.start_date = min(start_candidates)

    end_candidates = []
    for sub_task in sub_tasks:
        if not sub_task.start_date:
            continue
        normalized_start = _normalize_datetime(sub_task.start_date)
        estimated_duration = timedelta(
            days=sub_task.estimated_days or 0,
            hours=sub_task.estimated_hours or 0,
        )
        end_candidates.append(normalized_start + estimated_duration)

    task.end_date = max(end_candidates) if end_candidates else task.start_date


def sync_task_completion_status(db: Session, task_id: int):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    total_subtasks = (
        db.query(func.count(SubTask.id)).filter(SubTask.task_id == task_id).scalar() or 0
    )

    if total_subtasks == 0:
        return

    completed_subtasks = (
        db.query(func.count(SubTask.id))
        .filter(SubTask.task_id == task_id)
        .filter(SubTask.status == SubTaskStatus.complete.value)
        .scalar()
        or 0
    )

    if completed_subtasks == total_subtasks:
        task.status = TaskStatus.complete.value
    else:
        task.status = TaskStatus.in_progress.value


def ensure_user_can_manage_task(task: Task, user: User):
    if user.role == "admin":
        return

    if task.created_by == user.id:
        return

    if any(sub_task.assigned_to == user.id for sub_task in task.sub_tasks):
        return

    if task.parent_task_id is not None and task.parent_task and task.parent_task.created_by == user.id:
        return

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


def _enforce_admin_only_priority_fields(current_user: User, payload_fields: set[str]):
    if current_user.role == "admin":
        return

    restricted_fields = {"weightage_priority", "subtask_priority"}
    attempted_fields = sorted(restricted_fields.intersection(payload_fields))
    if attempted_fields:
        raise api_error(
            status_code=403,
            code="SUBTASK_PRIORITY_ADMIN_ONLY",
            message="Only admins can set or update weightage_priority and subtask_priority",
            details={"restricted_fields": attempted_fields},
        )


def _normalize_update_data(db: Session, sub_task: SubTask, update_data: dict):
    if "status" in update_data and update_data["status"] is not None:
        if (
            sub_task.status == SubTaskStatus.complete.value
            and update_data["status"].value != SubTaskStatus.complete.value
        ):
            raise api_error(
                status_code=400,
                code="SUBTASK_ALREADY_COMPLETE",
                message="A completed sub-task cannot be reopened",
            )
        update_data["status"] = update_data["status"].value

    if "subtask_priority" in update_data and update_data["subtask_priority"] is not None:
        if isinstance(update_data["subtask_priority"], SubTaskPriority):
            update_data["subtask_priority"] = update_data["subtask_priority"].value

    if "assigned_to_username" in update_data:
        username = update_data.pop("assigned_to_username")
        if username:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                raise api_error(
                    status_code=404,
                    code="ASSIGNED_USER_NOT_FOUND",
                    message="Assigned user not found",
                )
            update_data["assigned_to"] = user.id

    if "assigned_to" in update_data and update_data["assigned_to"] is not None:
        user = db.query(User).filter(User.id == update_data["assigned_to"]).first()
        if not user:
            raise api_error(
                status_code=404,
                code="ASSIGNED_USER_NOT_FOUND",
                message="Assigned user not found",
            )


def _validate_sub_task_update_constraints(db: Session, sub_task: SubTask, update_data: dict):
    validate_task(db, sub_task.task_id)
    validate_task(db, update_data.get("task_id", sub_task.task_id))


def _apply_sub_task_update(db: Session, sub_task: SubTask, update_data: dict):
    old_status = sub_task.status
    old_task_id = sub_task.task_id

    for key, value in update_data.items():
        setattr(sub_task, key, value)

    # Recalculate end_date if any relevant fields changed
    if any(field in update_data for field in ['start_date', 'estimated_days', 'estimated_hours']):
        if sub_task.start_date:
            sub_task.end_date = sub_task.start_date + timedelta(days=sub_task.estimated_days, hours=sub_task.estimated_hours)
        else:
            sub_task.end_date = None

    if old_status != TaskStatus.complete.value and sub_task.status == TaskStatus.complete.value:
        sub_task.completed_at = datetime.utcnow()
        _auto_fill_actual_time_on_completion(sub_task)
    elif old_status == SubTaskStatus.complete.value and sub_task.status != SubTaskStatus.complete.value:
        sub_task.completed_at = None

    recalculate_task_estimated_time(db, old_task_id)
    sync_task_completion_status(db, old_task_id)
    if sub_task.task_id != old_task_id:
        recalculate_task_estimated_time(db, sub_task.task_id)
        sync_task_completion_status(db, sub_task.task_id)


def _create_sub_task_record(
    db: Session,
    current_user: User,
    sub_task_payload: SubTaskCreate,
):
    task = validate_task(db, sub_task_payload.task_id)
    ensure_user_can_manage_task(task, current_user)
    task_non_priority_flag = task.non_priority_flag

    if current_user.role != "admin":
        # Non-admin: Check if they tried to set restricted fields
        _enforce_admin_only_priority_fields(current_user, set(sub_task_payload.__fields_set__))

    assigned_user = resolve_assigned_user(
        db=db,
        assigned_to=sub_task_payload.assigned_to,
        assigned_to_username=sub_task_payload.assigned_to_username,
        current_user=current_user,
    )

    needs_priority_approval = False
    if not task_non_priority_flag and (
        sub_task_payload.weightage_priority is None or sub_task_payload.subtask_priority is None
    ):
        if current_user.role == "admin":
            raise api_error(
                status_code=400,
                code="MISSING_PRIORITY_SUBTASK_FIELDS",
                message="Priority sub-task must include weightage_priority and subtask_priority",
            )
        needs_priority_approval = True

    raw_weightage_priority = 0
    if not task_non_priority_flag and sub_task_payload.weightage_priority is not None:
        raw_weightage_priority = sub_task_payload.weightage_priority

    weightage_priority = (
        0
        if task_non_priority_flag or sub_task_payload.weightage_priority is None
        else sub_task_payload.weightage_priority
    )
    subtask_priority = (
        SubTaskPriority.medium.value
        if task_non_priority_flag or sub_task_payload.subtask_priority is None
        else sub_task_payload.subtask_priority.value
    )

    new_sub_task = SubTask(
        title=sub_task_payload.title,
        description=sub_task_payload.description,
        status=sub_task_payload.status.value,
        non_priority_flag=task_non_priority_flag,
        raw_weightage_priority=raw_weightage_priority,
        weightage_priority=weightage_priority,
        subtask_priority=subtask_priority,
        estimated_days=sub_task_payload.estimated_days,
        estimated_hours=sub_task_payload.estimated_hours,
        start_date=sub_task_payload.start_date,
        end_date=(
            sub_task_payload.start_date + timedelta(days=sub_task_payload.estimated_days, hours=sub_task_payload.estimated_hours)
            if sub_task_payload.start_date
            else None
        ),
        actual_days=sub_task_payload.actual_days,
        actual_hours=sub_task_payload.actual_hours,
        task_id=sub_task_payload.task_id,
        created_by=current_user.id,
        assigned_to=assigned_user.id,
    )

    if new_sub_task.status == SubTaskStatus.complete.value:
        completion_time = datetime.utcnow()
        new_sub_task.completed_at = completion_time
        _auto_fill_actual_time_on_completion(new_sub_task)

    db.add(new_sub_task)
    db.flush()

    if not task_non_priority_flag and sub_task_payload.weightage_priority is not None:
        _rebalance_task_weightage_priorities(db, task.id)

    recalculate_task_estimated_time(db, sub_task_payload.task_id)
    sync_task_completion_status(db, sub_task_payload.task_id)
    db.commit()
    db.refresh(new_sub_task)

    if current_user.role != "admin" and needs_priority_approval:
        approval_request = SubTaskUpdateRequest(
            sub_task_id=new_sub_task.id,
            requested_by=current_user.id,
            status=SubTaskUpdateRequestStatus.pending.value,
            requested_changes={
                "priority_fields_pending": True,
                "note": "Waiting for admin to set weightage_priority and subtask_priority",
            },
        )
        db.add(approval_request)
        log_audit_event(
            db=db,
            action="CREATE",
            entity_type="sub_task_update_request",
            entity_id=new_sub_task.id,
            user_id=current_user.id,
            message="Sub-task created, waiting for admin to set priority fields",
            details={"sub_task_id": new_sub_task.id, "title": new_sub_task.title},
        )
        db.commit()

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


@router.post("/subtasks", response_model=SubTaskResponse | list[SubTaskResponse])
def create_sub_task(
    payload: SubTaskCreate | list[SubTaskCreate],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if isinstance(payload, list):
        created_sub_tasks = [
            _create_sub_task_record(db, current_user, sub_task)
            for sub_task in payload
        ]
        affected_task_ids = sorted({sub_task.task_id for sub_task in created_sub_tasks})
        for task_id in affected_task_ids:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task and not task.non_priority_flag:
                _rebalance_task_weightage_priorities(db, task_id)
        db.commit()
        for sub_task in created_sub_tasks:
            db.refresh(sub_task)
        return [_serialize_sub_task(sub_task) for sub_task in created_sub_tasks]

    new_sub_task = _create_sub_task_record(db, current_user, payload)
    fresh_sub_task = db.query(SubTask).filter(SubTask.id == new_sub_task.id).first() or new_sub_task
    return _serialize_sub_task(fresh_sub_task)


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
            or_(Task.created_by == current_user.id, SubTask.assigned_to == current_user.id)
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
        "items": [_serialize_sub_task(item) for item in items],
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
    return _serialize_sub_task(sub_task)


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
    if not update_data:
        raise api_error(
            status_code=400,
            code="EMPTY_UPDATE_PAYLOAD",
            message="Provide at least one field to update",
        )

    _enforce_admin_only_priority_fields(current_user, set(update_data.keys()))

    _normalize_update_data(db, sub_task, update_data)
    target_task_id = update_data.get("task_id", sub_task.task_id)
    target_task = validate_task(db, target_task_id)
    old_task_id = sub_task.task_id
    if target_task.non_priority_flag:
        update_data["weightage_priority"] = 0
        update_data["subtask_priority"] = SubTaskPriority.medium.value

    _validate_sub_task_update_constraints(db, sub_task, update_data)

    if current_user.role != "admin" and not target_task.non_priority_flag:
        pending_request = (
            db.query(SubTaskUpdateRequest)
            .filter(SubTaskUpdateRequest.sub_task_id == sub_task.id)
            .filter(SubTaskUpdateRequest.requested_by == current_user.id)
            .filter(SubTaskUpdateRequest.status == SubTaskUpdateRequestStatus.pending.value)
            .first()
        )

        if pending_request:
            raise api_error(
                status_code=409,
                code="SUBTASK_UPDATE_REQUEST_ALREADY_PENDING",
                message="You already have a pending update request for this sub-task",
            )

        request = SubTaskUpdateRequest(
            sub_task_id=sub_task.id,
            requested_by=current_user.id,
            status=SubTaskUpdateRequestStatus.pending.value,
            requested_changes=update_data,
        )
        db.add(request)

        log_audit_event(
            db=db,
            action="CREATE",
            entity_type="sub_task_update_request",
            entity_id=sub_task.id,
            user_id=current_user.id,
            message="Sub-task update approval requested",
            details={"requested_fields": list(update_data.keys())},
        )
        db.commit()
        db.refresh(request)
        return _serialize_sub_task(sub_task)

    _apply_sub_task_update(db, sub_task, update_data)

    if target_task_id != old_task_id:
        old_task = validate_task(db, old_task_id)
        if not old_task.non_priority_flag:
            _rebalance_task_weightage_priorities(db, old_task_id)
        if not target_task.non_priority_flag:
            _rebalance_task_weightage_priorities(db, target_task_id)
    elif not target_task.non_priority_flag and "weightage_priority" in update_data:
        _rebalance_task_weightage_priorities(db, target_task_id)

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
    return _serialize_sub_task(sub_task)

@router.put("/subtasks/{sub_task_id}/complete", response_model=SubTaskResponse)
def complete_sub_task(
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
        raise api_error(
            status_code=404,
            code="TASK_NOT_FOUND",
            message="Task not found",
        )

    ensure_user_can_manage_task(task, current_user)

    if sub_task.status == SubTaskStatus.complete.value:
        raise api_error(
            status_code=400,
            code="SUBTASK_ALREADY_COMPLETE",
            message="Sub task is already completed",
        )

    sub_task.status = SubTaskStatus.complete.value
    sub_task.completed_at = datetime.utcnow()

    _auto_fill_actual_time_on_completion(sub_task)

    db.flush()

    sync_task_completion_status(db, sub_task.task_id)

    log_audit_event(
        db=db,
        action="COMPLETE",
        entity_type="sub_task",
        entity_id=sub_task.id,
        user_id=current_user.id,
        message="Sub task completed",
        details={"task_id": sub_task.task_id},
    )

    db.commit()
    db.refresh(sub_task)

    return _serialize_sub_task(sub_task)


@router.get("/subtask-update-requests/my", response_model=SubTaskUpdateRequestListResponse)
def get_my_sub_task_update_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    query = db.query(SubTaskUpdateRequest).filter(
        SubTaskUpdateRequest.requested_by == current_user.id
    )

    total = query.count()
    items = (
        query.order_by(SubTaskUpdateRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_serialize_sub_task_update_request(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/subtask-update-requests", response_model=SubTaskUpdateRequestListResponse)
def get_all_sub_task_update_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    query = db.query(SubTaskUpdateRequest)
    if status:
        query = query.filter(SubTaskUpdateRequest.status == status)

    total = query.count()
    items = (
        query.order_by(SubTaskUpdateRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_serialize_sub_task_update_request(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.put("/subtask-update-requests/{request_id}/approve", response_model=SubTaskUpdateRequestResponse)
def approve_sub_task_update_request(
    request_id: int,
    payload: SubTaskUpdateRequestDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    request = db.query(SubTaskUpdateRequest).filter(SubTaskUpdateRequest.id == request_id).first()
    if not request:
        raise api_error(
            status_code=404,
            code="SUBTASK_UPDATE_REQUEST_NOT_FOUND",
            message="Sub-task update request not found",
        )

    if request.status != SubTaskUpdateRequestStatus.pending.value:
        raise api_error(
            status_code=400,
            code="SUBTASK_UPDATE_REQUEST_ALREADY_REVIEWED",
            message="Request is already reviewed",
        )

    sub_task = db.query(SubTask).filter(SubTask.id == request.sub_task_id).first()
    if not sub_task:
        raise api_error(
            status_code=404,
            code="SUBTASK_NOT_FOUND",
            message="Sub task not found",
        )

    update_data = dict(request.requested_changes or {})
    _normalize_update_data(db, sub_task, update_data)
    target_task_id = update_data.get("task_id", sub_task.task_id)
    target_task = validate_task(db, target_task_id)
    if target_task.non_priority_flag:
        update_data["weightage_priority"] = 0
        update_data["subtask_priority"] = SubTaskPriority.medium.value

    _validate_sub_task_update_constraints(db, sub_task, update_data)
    _apply_sub_task_update(db, sub_task, update_data)

    request.status = SubTaskUpdateRequestStatus.approved.value
    request.review_comment = payload.comment
    request.reviewed_by = current_user.id
    request.reviewed_at = datetime.utcnow()

    log_audit_event(
        db=db,
        action="APPROVE",
        entity_type="sub_task_update_request",
        entity_id=request.id,
        user_id=current_user.id,
        message="Sub-task update request approved",
        details={"sub_task_id": request.sub_task_id},
    )
    db.commit()
    db.refresh(request)
    return _serialize_sub_task_update_request(request)


@router.put("/subtask-update-requests/{request_id}/reject", response_model=SubTaskUpdateRequestResponse)
def reject_sub_task_update_request(
    request_id: int,
    payload: SubTaskUpdateRequestDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    request = db.query(SubTaskUpdateRequest).filter(SubTaskUpdateRequest.id == request_id).first()
    if not request:
        raise api_error(
            status_code=404,
            code="SUBTASK_UPDATE_REQUEST_NOT_FOUND",
            message="Sub-task update request not found",
        )

    if request.status != SubTaskUpdateRequestStatus.pending.value:
        raise api_error(
            status_code=400,
            code="SUBTASK_UPDATE_REQUEST_ALREADY_REVIEWED",
            message="Request is already reviewed",
        )

    request.status = SubTaskUpdateRequestStatus.rejected.value
    request.review_comment = payload.comment
    request.reviewed_by = current_user.id
    request.reviewed_at = datetime.utcnow()

    log_audit_event(
        db=db,
        action="REJECT",
        entity_type="sub_task_update_request",
        entity_id=request.id,
        user_id=current_user.id,
        message="Sub-task update request rejected",
        details={"sub_task_id": request.sub_task_id},
    )
    db.commit()
    db.refresh(request)
    return _serialize_sub_task_update_request(request)


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

    remaining_priority_sub_tasks = (
        db.query(SubTask)
        .filter(SubTask.task_id == sub_task.task_id)
        .filter(SubTask.id != sub_task.id)
        .all()
    )

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

    db.query(SubTaskUpdateRequest).filter(
        SubTaskUpdateRequest.sub_task_id == sub_task.id
    ).delete(synchronize_session=False)
    db.query(SubTask).filter(SubTask.id == sub_task.id).delete(synchronize_session=False)
    if remaining_priority_sub_tasks and not task.non_priority_flag:
        _rebalance_task_weightage_priorities(db, task_id)
    recalculate_task_estimated_time(db, task_id)
    sync_task_completion_status(db, task_id)
    db.commit()

    return {"message": "Sub task deleted successfully"}
