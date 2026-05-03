from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db, require_role
import logging
from app.core.database import SessionLocal
from app.models.sub_task import SubTask, SubTaskStatus, SubTaskPriority
from app.models.task_creation_request import TaskCreationRequest, TaskCreationRequestStatus
from app.models.sub_task_update_request import SubTaskUpdateRequest, SubTaskUpdateRequestStatus
from app.models.task import Task, TaskStatus
from app.models.task_update_request import TaskUpdateRequest, TaskUpdateRequestStatus
from app.models.user import User
from app.routers.sub_tasks import (
    ensure_user_can_manage_task,
    get_task_weightage_priority_total,
    recalculate_task_estimated_time,
    resolve_assigned_user,
    sync_task_completion_status,
    validate_weightage_priority_total,
)
from app.schemas.task import (
    TaskPriorityBulkUpdateRequest,
    TaskPriorityBulkUpdateResponse,
    TaskAdminListResponse,
    TaskAdminResponse,
    TaskCreationRequestDecision,
    TaskCreationRequestListResponse,
    TaskCreationRequestResponse,
    TaskCreate,
    TaskCreateResponse,
    TaskListResponse,
    TaskProgressResponse,
    TaskResponse,
    TaskTimelineResponse,
    TaskVersionBumpRequest,
    TaskUpdateRequestDecision,
    TaskUpdateRequestListResponse,
    TaskUpdateRequestResponse,
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
        "non_priority_flag": sub_task.non_priority_flag,
        "weightage_priority": sub_task.weightage_priority,
        "subtask_priority": sub_task.subtask_priority,
        "estimated_days": sub_task.estimated_days,
        "estimated_hours": sub_task.estimated_hours,
        "start_date": sub_task.start_date,
        "end_date": sub_task.calculate_end_date() if sub_task.start_date else None,
        "actual_days": sub_task.actual_days,
        "actual_hours": sub_task.actual_hours,
        "created_at": sub_task.created_at,
        "completed_at": sub_task.completed_at,
        "task_id": sub_task.task_id,
        "created_by": _serialize_user_reference(sub_task.creator, sub_task.created_by),
        "assigned_to": _serialize_user_reference(sub_task.assignee, sub_task.assigned_to),
    }


def _to_hours(days: int, hours: int) -> float:
    return float((days * 24) + hours)


def _serialize_task(task: Task, include_sub_tasks: bool = False):
    payload = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "estimated_days": task.estimated_days,
        "estimated_hours": task.estimated_hours,
        "start_date": task.start_date,
        "end_date": task.end_date,
        "created_by": _serialize_user_reference(task.creator, task.created_by),
        "version": f"{task.version_major}.{task.version_minor}.{task.version_patch}",
        "parent_task_id": task.parent_task_id,
    }

    if include_sub_tasks:
        payload["sub_tasks"] = [_serialize_sub_task(sub_task) for sub_task in task.sub_tasks]

    return payload


def _serialize_task_update_request(request: TaskUpdateRequest):
    return {
        "id": request.id,
        "task_id": request.task_id,
        "requested_by": _serialize_user_reference(request.requester, request.requested_by),
        "status": request.status,
        "requested_changes": request.requested_changes,
        "review_comment": request.review_comment,
        "reviewed_by": _serialize_user_reference(request.reviewer, request.reviewed_by),
        "created_at": request.created_at,
        "reviewed_at": request.reviewed_at,
    }


def _serialize_task_creation_request(request: TaskCreationRequest):
    return {
        "id": request.id,
        "requested_by": _serialize_user_reference(request.requester, request.requested_by),
        "status": request.status,
        "requested_payload": request.requested_payload,
        "review_comment": request.review_comment,
        "reviewed_by": _serialize_user_reference(request.reviewer, request.reviewed_by),
        "approved_task_id": request.approved_task_id,
        "created_at": request.created_at,
        "reviewed_at": request.reviewed_at,
    }


def _enforce_admin_only_task_fields(current_user: User, task: TaskCreate):
    """Ensure non-admins don't set restricted fields in task or nested subtasks."""
    if current_user.role == "admin":
        return

    restricted_task_fields = {"weightage_priority", "subtask_priority", "non_priority_flag"}

    # Check nested subtasks
    if task.sub_tasks:
        for idx, sub_task in enumerate(task.sub_tasks):
            # Only check fields that were explicitly set by the user
            fields_set = getattr(sub_task, "model_fields_set", set())
            attempted_fields = sorted(restricted_task_fields.intersection(fields_set))
            if attempted_fields:
                raise api_error(
                    status_code=403,
                    code="TASK_PRIORITY_ADMIN_ONLY",
                    message="Only admins can set weightage_priority, subtask_priority, and non_priority_flag in sub-tasks",
                    details={"sub_task_index": idx, "restricted_fields": attempted_fields},
                )


def _validate_priority_sub_tasks_ready_for_creation(task: TaskCreate):
    """Validate weightage before creation."""
    if not task.sub_tasks:
        return

    missing_weightage = []
    invalid_weightage = []

    for idx, sub_task in enumerate(task.sub_tasks):
        if not sub_task.non_priority_flag:
            if sub_task.weightage_priority is None:
                missing_weightage.append(idx)
            elif not isinstance(sub_task.weightage_priority, (int, float)) or sub_task.weightage_priority < 0:
                invalid_weightage.append({"index": idx, "value": sub_task.weightage_priority})

    if missing_weightage:
        raise api_error(
            status_code=400,
            code="MISSING_SUBTASK_WEIGHTAGE_PRIORITY",
            message="Admin must set explicit weightage_priority for all priority sub-tasks (cannot default)",
            details={"sub_task_indices": missing_weightage},
        )

    if invalid_weightage:
        raise api_error(
            status_code=400,
            code="INVALID_SUBTASK_WEIGHTAGE_PRIORITY",
            message="Weightage priority must be non-negative number",
            details={"invalid_weightages": invalid_weightage},
        )
    has_priority = any(not getattr(st, "non_priority_flag", False) for st in task.sub_tasks)
    if not has_priority:
        raise api_error(
            status_code=400,
            code="NO_PRIORITY_SUBTASKS",
            message="Provide at least one priority sub-task with weightage_priority",
        )


def _validate_approved_payload_safe_override(original_task: TaskCreate, override_task: TaskCreate | None) -> dict:
    """Ensure approved_payload only modifies priority-related fields, not core task properties.
    Returns dict of changes for audit logging."""
    changes = {}
    if override_task is None:
        return changes

    payload_version = getattr(override_task, "__payload_version__", 1)
    if payload_version > getattr(TaskCreate, "__payload_version__", 1):
        raise api_error(
            status_code=400,
            code="UNSUPPORTED_OVERRIDE_PAYLOAD_VERSION",
            message="Override payload schema version is not supported",
            details={"provided_version": payload_version, "supported_version": getattr(TaskCreate, "__payload_version__", 1)},
        )

    # Top-level whitelist: only `sub_tasks` may be provided in an override
    provided_top_level = getattr(override_task, "model_fields_set", set())
    allowed_top_level = {"sub_tasks"}
    extra_top = provided_top_level.difference(allowed_top_level)
    if extra_top:
        raise api_error(
            status_code=400,
            code="INVALID_OVERRIDE_TOP_LEVEL_FIELDS",
            message="Override may only include sub_tasks",
            details={"invalid_fields": sorted(list(extra_top))},
        )

    # Check if core task fields were changed
    if override_task.title != original_task.title:
        raise api_error(
            status_code=400,
            code="INVALID_OVERRIDE_FIELD",
            message="Admin can only override sub_tasks priority fields, not task title",
        )
    if override_task.description != original_task.description:
        raise api_error(
            status_code=400,
            code="INVALID_OVERRIDE_FIELD",
            message="Admin can only override sub_tasks priority fields, not task description",
        )

    if override_task.sub_tasks is None and original_task.sub_tasks is not None:
        raise api_error(
            status_code=400,
            code="INVALID_OVERRIDE_SUBTASKS_NULL",
            message="Cannot remove all sub_tasks in override - sub_tasks must remain",
        )

    if override_task.sub_tasks and original_task.sub_tasks:
        def _fingerprint_from_obj(st):
            title = getattr(st, "title", None) or (st.get("title") if isinstance(st, dict) else "")
            desc = getattr(st, "description", None) or (st.get("description") if isinstance(st, dict) else "")
            days = getattr(st, "estimated_days", None) or (st.get("estimated_days") if isinstance(st, dict) else "")
            hours = getattr(st, "estimated_hours", None) or (st.get("estimated_hours") if isinstance(st, dict) else "")
            assignee = getattr(st, "assigned_to_username", None) or (st.get("assigned_to_username") if isinstance(st, dict) else "")
            return f"{str(title).strip().lower()}|{str(desc).strip().lower()}|{str(days)}|{str(hours)}|{str(assignee).strip().lower()}"

        orig_map: dict[str, list[int]] = {}

        # If the original TaskCreate has stored fingerprints, prefer them
        stored_client_ids = getattr(original_task, "_stored_subtask_client_ids", None)
        stored_fps = getattr(original_task, "_stored_subtask_fingerprints", None)

        # Prefer client id mapping if present
        if stored_client_ids and isinstance(stored_client_ids, list) and len(stored_client_ids) == len(original_task.sub_tasks):
            for idx, cid in enumerate(stored_client_ids):
                if cid is not None:
                    orig_map.setdefault(f"client:{cid}", []).append(idx)

        # Fallback to fingerprint mapping
        if stored_fps and isinstance(stored_fps, list) and len(stored_fps) == len(original_task.sub_tasks):
            for idx, fp in enumerate(stored_fps):
                orig_map.setdefault(fp, []).append(idx)
        else:
            for idx, st in enumerate(original_task.sub_tasks):
                fp = _fingerprint_from_obj(st)
                orig_map.setdefault(fp, []).append(idx)

        subtask_changes = []
        # For each override subtask, find matching original
        for override_st in override_task.sub_tasks:
            # If override provides a client_subtask_id, try client mapping first
            client_id = getattr(override_st, "client_subtask_id", None) or (override_st.get("client_subtask_id") if isinstance(override_st, dict) else None)
            matched = False
            if client_id is not None and f"client:{client_id}" in orig_map and orig_map[f"client:{client_id}"]:
                orig_idx = orig_map[f"client:{client_id}"].pop(0)
                orig_st = original_task.sub_tasks[orig_idx]
                matched = True
            else:
                fp = _fingerprint_from_obj(override_st)
                if fp not in orig_map or not orig_map[fp]:
                    raise api_error(
                        status_code=400,
                        code="UNMATCHED_OVERRIDE_SUBTASK",
                        message="Override sub_task does not match any original sub_task by fingerprint",
                        details={"fingerprint": fp, "client_id": client_id},
                    )
                orig_idx = orig_map[fp].pop(0)
                orig_st = original_task.sub_tasks[orig_idx]
                matched = True

            # Per-subtask whitelist of allowed override fields
            provided_fields = getattr(override_st, "model_fields_set", set())
            allowed_fields = {"weightage_priority", "subtask_priority", "non_priority_flag"}
            extra = set(provided_fields) - allowed_fields
            if extra:
                raise api_error(
                    status_code=400,
                    code="INVALID_OVERRIDE_SUBTASK_FIELDS",
                    message="Override sub_task contains disallowed fields",
                    details={"sub_task_index": orig_idx, "invalid_fields": sorted(list(extra))},
                )

            # Track changes for audit logging
            st_changes = {}
            if getattr(override_st, "weightage_priority", None) != getattr(orig_st, "weightage_priority", None):
                st_changes["weightage_priority"] = {
                    "from": getattr(orig_st, "weightage_priority", None),
                    "to": getattr(override_st, "weightage_priority", None),
                }
            if getattr(override_st, "subtask_priority", None) != getattr(orig_st, "subtask_priority", None):
                st_changes["subtask_priority"] = {
                    "from": getattr(orig_st, "subtask_priority", None),
                    "to": getattr(override_st, "subtask_priority", None),
                }
            if getattr(override_st, "non_priority_flag", None) != getattr(orig_st, "non_priority_flag", None):
                st_changes["non_priority_flag"] = {
                    "from": getattr(orig_st, "non_priority_flag", None),
                    "to": getattr(override_st, "non_priority_flag", None),
                }
            if st_changes:
                subtask_changes.append({"index": orig_idx, "changes": st_changes})

        if subtask_changes:
            changes["sub_tasks"] = subtask_changes

    return changes


def _create_task_from_payload(
    db: Session,
    task: TaskCreate,
    *,
    creator_id: int,
    current_user: User,
):
    _validate_priority_sub_tasks_ready_for_creation(task)

    new_task = Task(
        title=task.title,
        description=task.description,
        created_by=creator_id,
    )

    db.add(new_task)
    created_sub_tasks: list[SubTask] = []
    db.flush()

    if task.sub_tasks:
        priority_sub_tasks = [sub_task for sub_task in task.sub_tasks if not sub_task.non_priority_flag]
        if priority_sub_tasks:
            # All weightage_priority values must be explicit (checked earlier); sum without fallback
            validate_weightage_priority_total(sum(sub_task.weightage_priority for sub_task in priority_sub_tasks))

        for sub_task in task.sub_tasks:
            assigned_user = resolve_assigned_user(
                db=db,
                assigned_to=sub_task.assigned_to,
                assigned_to_username=sub_task.assigned_to_username,
                current_user=current_user,
            )

            if not sub_task.non_priority_flag and sub_task.weightage_priority is None:
                raise api_error(
                    status_code=400,
                    code="MISSING_PRIORITY_SUBTASK_WEIGHTAGE",
                    message="Priority subtask must have explicit weightage_priority, cannot default to 0",
                    details={"title": sub_task.title},
                )

            weightage_priority = 0 if sub_task.non_priority_flag else sub_task.weightage_priority
            subtask_priority = sub_task.subtask_priority.value if sub_task.subtask_priority else SubTaskPriority.medium.value

            new_sub_task = SubTask(
                title=sub_task.title,
                description=sub_task.description,
                status=sub_task.status.value,
                non_priority_flag=sub_task.non_priority_flag,
                weightage_priority=weightage_priority,
                subtask_priority=subtask_priority,
                estimated_days=sub_task.estimated_days,
                estimated_hours=sub_task.estimated_hours,
                start_date=sub_task.start_date,
                end_date=(
                    sub_task.start_date
                    + timedelta(days=sub_task.estimated_days, hours=sub_task.estimated_hours)
                    if sub_task.start_date
                    else None
                ),
                actual_days=sub_task.actual_days,
                actual_hours=sub_task.actual_hours,
                task_id=new_task.id,
                created_by=creator_id,
                assigned_to=assigned_user.id,
            )
            db.add(new_sub_task)
            db.flush()
            created_sub_tasks.append(new_sub_task)

    recalculate_task_estimated_time(db, new_task.id)
    sync_task_completion_status(db, new_task.id)

    return new_task, created_sub_tasks


@router.post("/tasks", response_model=TaskCreateResponse | TaskCreationRequestResponse)
def create_task(
    task: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        # Validate that non-admins don't try to set restricted priority fields
        _enforce_admin_only_task_fields(current_user, task)

        # Store payload with explicit version wrapper and fingerprints
        payload_wrapper = jsonable_encoder(task)
        def _fingerprint_obj(st):
            title = st.title or ""
            desc = st.description or ""
            days = st.estimated_days if st.estimated_days is not None else ""
            hours = st.estimated_hours if st.estimated_hours is not None else ""
            assignee = getattr(st, "assigned_to_username", "") or ""
            return f"{str(title).strip().lower()}|{str(desc).strip().lower()}|{str(days)}|{str(hours)}|{str(assignee).strip().lower()}"

        subtask_fps = []
        subtask_client_ids = []
        if getattr(task, "sub_tasks", None):
            for st in task.sub_tasks:
                subtask_fps.append(_fingerprint_obj(st))
                subtask_client_ids.append(getattr(st, "client_subtask_id", None))

        if isinstance(payload_wrapper, dict):
            payload_wrapper = {
                "payload": payload_wrapper,
                "version": getattr(TaskCreate, "__payload_version__", 1),
                "subtask_fingerprints": subtask_fps,
                "subtask_client_ids": subtask_client_ids,
            }

        creation_request = TaskCreationRequest(
            requested_by=current_user.id,
            status=TaskCreationRequestStatus.pending.value,
            requested_payload=payload_wrapper,
        )
        db.add(creation_request)
        db.flush()

        log_audit_event(
            db=db,
            action="CREATE",
            entity_type="task_creation_request",
            entity_id=creation_request.id,
            user_id=current_user.id,
            message="Task creation approval requested",
            details={"title": task.title, "sub_tasks_count": len(task.sub_tasks or [])},
        )
        db.commit()
        db.refresh(creation_request)
        return _serialize_task_creation_request(creation_request)

    try:
        new_task, created_sub_tasks = _create_task_from_payload(
            db,
            task,
            creator_id=current_user.id,
            current_user=current_user,
        )
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
            "sub_tasks_count": len(created_sub_tasks),
        },
    )
    db.commit()
    return {
        **_serialize_task(new_task, include_sub_tasks=True),
        "sub_tasks": [_serialize_sub_task(sub_task) for sub_task in created_sub_tasks],
        "sub_tasks_created_count": len(created_sub_tasks),
    }


@router.get("/task-creation-requests/my", response_model=TaskCreationRequestListResponse)
def get_my_task_creation_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    query = db.query(TaskCreationRequest).filter(TaskCreationRequest.requested_by == current_user.id)

    total = query.count()
    items = (
        query.order_by(TaskCreationRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_serialize_task_creation_request(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/task-creation-requests", response_model=TaskCreationRequestListResponse)
def get_all_task_creation_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    query = db.query(TaskCreationRequest)
    if status:
        query = query.filter(TaskCreationRequest.status == status)

    total = query.count()
    items = (
        query.order_by(TaskCreationRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_serialize_task_creation_request(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.put("/task-creation-requests/{request_id}/approve", response_model=TaskCreationRequestResponse)
def approve_task_creation_request(
    request_id: int,
    payload: TaskCreationRequestDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    logger = logging.getLogger(__name__)

    # Use explicit transaction boundary so the row lock is held for the duration
    try:
        with db.begin():
            request = (
                db.query(TaskCreationRequest)
                .filter(TaskCreationRequest.id == request_id)
                .with_for_update(nowait=False)
                .first()
            )
            if not request:
                raise api_error(
                    status_code=404,
                    code="TASK_CREATION_REQUEST_NOT_FOUND",
                    message="Task creation request not found",
                )

            if request.status != TaskCreationRequestStatus.pending.value:
                raise api_error(
                    status_code=400,
                    code="TASK_CREATION_REQUEST_ALREADY_REVIEWED",
                    message="Request is already reviewed",
                )

            # Ensure requester still exists and is active
            requester = db.query(User).filter(User.id == request.requested_by).first()
            if not requester:
                raise api_error(
                    status_code=400,
                    code="REQUESTER_NOT_FOUND",
                    message="User who requested this task no longer exists",
                )
            if hasattr(requester, "is_active") and not requester.is_active:
                raise api_error(
                    status_code=400,
                    code="REQUESTER_INACTIVE",
                    message="User who requested this task is inactive",
                )

            # Parse stored payload (support legacy and wrapped payload)
            stored = request.requested_payload
            if isinstance(stored, dict) and "payload" in stored:
                payload_body = stored["payload"]
                stored_version = stored.get("version", 1)
            else:
                payload_body = stored
                stored_version = 1

            try:
                original_task = TaskCreate(**payload_body)
                # attach stored fingerprints to the TaskCreate instance for later matching
                if isinstance(stored, dict):
                    if "subtask_fingerprints" in stored:
                        setattr(original_task, "_stored_subtask_fingerprints", stored.get("subtask_fingerprints"))
                    if "subtask_client_ids" in stored:
                        setattr(original_task, "_stored_subtask_client_ids", stored.get("subtask_client_ids"))
                # enforce stored payload version compatibility
                stored_version = stored.get("version", 1) if isinstance(stored, dict) else 1
                if stored_version > getattr(TaskCreate, "__payload_version__", 1):
                    raise api_error(
                        status_code=400,
                        code="UNSUPPORTED_STORED_PAYLOAD_VERSION",
                        message="Stored task payload version is newer than supported by this service",
                        details={"stored_version": stored_version, "supported_version": getattr(TaskCreate, "__payload_version__", 1)},
                    )
            except Exception as exc:
                # Audit failure in separate session; don't let audit errors break main flow
                try:
                    separate_session = SessionLocal()
                    log_audit_event(
                        db=separate_session,
                        action="APPROVE_FAILED",
                        entity_type="task_creation_request",
                        entity_id=request.id,
                        user_id=current_user.id,
                        message="Task creation request approval failed - deserialization error",
                        details={"error": str(exc)},
                    )
                    separate_session.commit()
                    separate_session.close()
                except Exception as audit_exc:
                    logger.exception("Failed to write separate audit log: %s", audit_exc)
                raise api_error(
                    status_code=400,
                    code="INVALID_STORED_PAYLOAD",
                    message="Stored task payload is corrupted or invalid",
                    dev_message=str(exc),
                )

            override_diff = {}
            if payload.approved_payload:
                override_diff = _validate_approved_payload_safe_override(original_task, payload.approved_payload)

            task_payload = payload.approved_payload or original_task

            # Create the task (will be committed with this transaction)
            try:
                new_task, created_sub_tasks = _create_task_from_payload(
                    db,
                    task_payload,
                    creator_id=request.requested_by,
                    current_user=current_user,
                )
            except Exception as exc:
                # Audit creation failure in separate session; keep main exception semantics
                try:
                    separate_session = SessionLocal()
                    log_audit_event(
                        db=separate_session,
                        action="APPROVE_FAILED",
                        entity_type="task_creation_request",
                        entity_id=request.id,
                        user_id=current_user.id,
                        message="Task creation request approval failed - task creation error",
                        details={"error": str(exc)},
                    )
                    separate_session.commit()
                    separate_session.close()
                except Exception as audit_exc:
                    logger.exception("Failed to write separate audit log for creation error: %s", audit_exc)
                raise

            # Update request as approved
            request.status = TaskCreationRequestStatus.approved.value
            request.review_comment = payload.comment
            request.reviewed_by = current_user.id
            request.reviewed_at = datetime.utcnow()
            request.approved_task_id = new_task.id

            # Include override diff in audit details
            audit_details = {
                "task_id": new_task.id,
                "sub_tasks_count": len(created_sub_tasks),
                "requested_payload": payload_body,
                "created_task_snapshot": {
                    **_serialize_task(new_task, include_sub_tasks=True),
                    "sub_tasks": [_serialize_sub_task(st) for st in created_sub_tasks],
                },
            }
            if override_diff:
                audit_details["override_diff"] = override_diff

            log_audit_event(
                db=db,
                action="APPROVE",
                entity_type="task_creation_request",
                entity_id=request.id,
                user_id=current_user.id,
                message="Task creation request approved",
                details=audit_details,
            )

            # leaving context manager will commit
            db.refresh(request)
            return _serialize_task_creation_request(request)
    except HTTPException:
        raise
    except Exception:
        # Unexpected exceptions should propagate (they'll rollback the transaction)
        raise


@router.put("/task-creation-requests/{request_id}/reject", response_model=TaskCreationRequestResponse)
def reject_task_creation_request(
    request_id: int,
    payload: TaskCreationRequestDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    request = db.query(TaskCreationRequest).filter(TaskCreationRequest.id == request_id).first()
    if not request:
        raise api_error(
            status_code=404,
            code="TASK_CREATION_REQUEST_NOT_FOUND",
            message="Task creation request not found",
        )

    if request.status != TaskCreationRequestStatus.pending.value:
        raise api_error(
            status_code=400,
            code="TASK_CREATION_REQUEST_ALREADY_REVIEWED",
            message="Request is already reviewed",
        )

    if not payload.comment or not payload.comment.strip():
        raise api_error(
            status_code=400,
            code="TASK_CREATION_REJECTION_REASON_REQUIRED",
            message="Rejection reason is required",
        )

    request.status = TaskCreationRequestStatus.rejected.value
    request.review_comment = payload.comment.strip()
    request.reviewed_by = current_user.id
    request.reviewed_at = datetime.utcnow()

    log_audit_event(
        db=db,
        action="REJECT",
        entity_type="task_creation_request",
        entity_id=request.id,
        user_id=current_user.id,
        message="Task creation request rejected",
        details={"requested_by": request.requested_by},
    )
    db.commit()
    db.refresh(request)
    return _serialize_task_creation_request(request)


@router.get("/my-tasks", response_model=TaskListResponse)
def get_my_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    query = db.query(Task).options(selectinload(Task.sub_tasks)).filter(
        or_(
            Task.created_by == current_user.id,
            Task.id.in_(db.query(SubTask.task_id).filter(SubTask.assigned_to == current_user.id)),
        )
    )

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

    ensure_user_can_manage_task(task, current_user)

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


@router.get("/task-update-requests/my", response_model=TaskUpdateRequestListResponse)
def get_my_task_update_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    query = db.query(TaskUpdateRequest).filter(TaskUpdateRequest.requested_by == current_user.id)

    total = query.count()
    items = (
        query.order_by(TaskUpdateRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_serialize_task_update_request(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/task-update-requests", response_model=TaskUpdateRequestListResponse)
def get_all_task_update_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    query = db.query(TaskUpdateRequest)
    if status:
        query = query.filter(TaskUpdateRequest.status == status)

    total = query.count()
    items = (
        query.order_by(TaskUpdateRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_serialize_task_update_request(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


def _apply_task_update(task: Task, update_data: dict):
    if "status" in update_data and update_data["status"] is not None:
        if task.status == TaskStatus.complete.value and update_data["status"].value != TaskStatus.complete.value:
            raise api_error(
                status_code=400,
                code="TASK_ALREADY_COMPLETE",
                message="A completed task cannot be reopened",
            )
        update_data["status"] = update_data["status"].value

    for key, value in update_data.items():
        setattr(task, key, value)


@router.put("/task-update-requests/{request_id}/approve", response_model=TaskUpdateRequestResponse)
def approve_task_update_request(
    request_id: int,
    payload: TaskUpdateRequestDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    request = db.query(TaskUpdateRequest).filter(TaskUpdateRequest.id == request_id).first()
    if not request:
        raise api_error(status_code=404, code="TASK_UPDATE_REQUEST_NOT_FOUND", message="Task update request not found")

    if request.status != TaskUpdateRequestStatus.pending.value:
        raise api_error(
            status_code=400,
            code="TASK_UPDATE_REQUEST_ALREADY_REVIEWED",
            message="Request is already reviewed",
        )

    task = db.query(Task).filter(Task.id == request.task_id).first()
    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    update_data = dict(request.requested_changes or {})
    _apply_task_update(task, update_data)

    request.status = TaskUpdateRequestStatus.approved.value
    request.review_comment = payload.comment
    request.reviewed_by = current_user.id
    request.reviewed_at = datetime.utcnow()

    log_audit_event(
        db=db,
        action="APPROVE",
        entity_type="task_update_request",
        entity_id=request.id,
        user_id=current_user.id,
        message="Task update request approved",
        details={"task_id": request.task_id},
    )
    db.commit()
    db.refresh(request)
    return _serialize_task_update_request(request)


@router.put("/task-update-requests/{request_id}/reject", response_model=TaskUpdateRequestResponse)
def reject_task_update_request(
    request_id: int,
    payload: TaskUpdateRequestDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    request = db.query(TaskUpdateRequest).filter(TaskUpdateRequest.id == request_id).first()
    if not request:
        raise api_error(status_code=404, code="TASK_UPDATE_REQUEST_NOT_FOUND", message="Task update request not found")

    if request.status != TaskUpdateRequestStatus.pending.value:
        raise api_error(
            status_code=400,
            code="TASK_UPDATE_REQUEST_ALREADY_REVIEWED",
            message="Request is already reviewed",
        )

    request.status = TaskUpdateRequestStatus.rejected.value
    request.review_comment = payload.comment
    request.reviewed_by = current_user.id
    request.reviewed_at = datetime.utcnow()

    log_audit_event(
        db=db,
        action="REJECT",
        entity_type="task_update_request",
        entity_id=request.id,
        user_id=current_user.id,
        message="Task update request rejected",
        details={"task_id": request.task_id},
    )
    db.commit()
    db.refresh(request)
    return _serialize_task_update_request(request)


@router.get("/tasks", response_model=TaskAdminListResponse)
def get_all_tasks_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    query = db.query(Task)

    if status:
        query = query.filter(Task.status == status)

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
                "start_date": task.start_date,
                "end_date": task.end_date,
                "created_by": _serialize_user_reference(task.creator, task.created_by),
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

    ensure_user_can_manage_task(task, current_user)

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

    ensure_user_can_manage_task(task, current_user)

    total_subtasks = (
        db.query(func.count(SubTask.id)).filter(SubTask.task_id == task_id).scalar() or 0
    )
    completed_subtasks = (
        db.query(func.count(SubTask.id))
        .filter(SubTask.task_id == task_id)
        .filter(SubTask.status == SubTaskStatus.complete.value)
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

    ensure_user_can_manage_task(task, current_user)

    total_estimated_hours = sum(
        _to_hours(sub_task.estimated_days, sub_task.estimated_hours)
        for sub_task in task.sub_tasks
    )
    total_actual_hours = sum(
        _to_hours(sub_task.actual_days, sub_task.actual_hours) for sub_task in task.sub_tasks
    )

    sub_task_count = len(task.sub_tasks)
    total_priority = sum(sub_task.weightage_priority for sub_task in task.sub_tasks)

    sub_tasks_timeline = []
    total_expected_hours = 0.0

    for sub_task in task.sub_tasks:
        if sub_task_count == 0:
            weight = 0.0
        elif total_priority > 0:
            weight = sub_task.weightage_priority / total_priority
        else:
            weight = 1.0 / sub_task_count

        expected_hours = (
            round(total_estimated_hours * weight, 2)
            if sub_task.status == SubTaskStatus.complete.value
            else 0.0
        )
        total_expected_hours += expected_hours

        sub_tasks_timeline.append(
            {
                "sub_task_id": sub_task.id,
                "title": sub_task.title,
                "status": sub_task.status,
                "priority": sub_task.weightage_priority,
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
    current_user: User = Depends(require_role("admin")),
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

    total_priority = sum(item.weightage_priority for item in payload.items)
    validate_weightage_priority_total(total_priority)

    priority_map = {item.sub_task_id: item.weightage_priority for item in payload.items}
    for sub_task in task.sub_tasks:
        sub_task.weightage_priority = priority_map[sub_task.id]

    db.flush()
    validate_weightage_priority_total(
        get_task_weightage_priority_total(db, task_id)
    )

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
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    update_data = task_update.dict(exclude_unset=True)

    if not update_data:
        raise api_error(
            status_code=400,
            code="EMPTY_UPDATE_PAYLOAD",
            message="Provide at least one field to update",
        )

    if current_user.role != "admin":
        pending_request = (
            db.query(TaskUpdateRequest)
            .filter(TaskUpdateRequest.task_id == task.id)
            .filter(TaskUpdateRequest.requested_by == current_user.id)
            .filter(TaskUpdateRequest.status == TaskUpdateRequestStatus.pending.value)
            .first()
        )

        if pending_request:
            raise api_error(
                status_code=409,
                code="TASK_UPDATE_REQUEST_ALREADY_PENDING",
                message="You already have a pending update request for this task",
            )

        if "status" in update_data and task.status == TaskStatus.complete.value:
            raise api_error(
                status_code=400,
                code="TASK_ALREADY_COMPLETE",
                message="A completed task cannot be reopened",
            )

        if "status" in update_data and update_data["status"] is not None:
            update_data["status"] = update_data["status"].value

        request = TaskUpdateRequest(
            task_id=task.id,
            requested_by=current_user.id,
            status=TaskUpdateRequestStatus.pending.value,
            requested_changes=update_data,
        )
        db.add(request)

        log_audit_event(
            db=db,
            action="CREATE",
            entity_type="task_update_request",
            entity_id=task.id,
            user_id=current_user.id,
            message="Task update approval requested",
            details={"requested_fields": list(update_data.keys())},
        )
        db.commit()
        db.refresh(request)
        return _serialize_task(task)

    _apply_task_update(task, update_data)

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
    payload: TaskVersionBumpRequest = TaskVersionBumpRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
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

    current_major = task.version_major
    current_minor = task.version_minor
    current_patch = task.version_patch

    if payload.bump_type == "major":
        next_major = current_major + 1
        next_minor = 0
        next_patch = 0
    elif payload.bump_type == "minor":
        next_major = current_major
        next_minor = current_minor + 1
        next_patch = 0
    else:
        next_major = current_major
        next_minor = current_minor
        next_patch = current_patch + 1

    new_version = Task(
        title=task.title,
        description=task.description,
        status=TaskStatus.not_complete.value,
        estimated_days=0,
        estimated_hours=0,
        created_by=current_user.id,
        version_major=next_major,
        version_minor=next_minor,
        version_patch=next_patch,
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
        details={
            "previous_task_id": task.id,
            "new_version": f"{next_major}.{next_minor}.{next_patch}",
            "bump_type": payload.bump_type,
        },
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
