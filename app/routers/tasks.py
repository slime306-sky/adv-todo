from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db, require_role
from app.core.timeline import (
    build_sub_task_timing_fields,
    calculate_task_behind_hours_from_sub_tasks,
)
import logging
from app.core.database import SessionLocal
from app.models.category import Category
from app.models.department import Department
from app.models.sub_task import SubTask, SubTaskStatus, SubTaskPriority
from app.models.task_creation_request import TaskCreationRequest, TaskCreationRequestStatus
from app.models.sub_task_update_request import SubTaskUpdateRequest, SubTaskUpdateRequestStatus, SubTaskUpdateRequestType
from app.models.task import Task, TaskStatus
from app.models.task_update_request import TaskUpdateRequest, TaskUpdateRequestStatus
from app.models.user import User
from app.routers.sub_tasks import (
    ensure_user_can_manage_task,
    recalculate_task_estimated_time,
    resolve_assigned_user,
    sync_task_completion_status,
    _normalize_weightage_priority_values,
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
    TaskSubTaskCreate,
    TaskVersionBumpRequest,
    TaskUpdateRequestDecision,
    TaskUpdateRequestListResponse,
    TaskUpdateRequestResponse,
    TaskWithSubTasksResponse,
    TaskUpdate,
)

router = APIRouter(tags=["tasks"])


def _has_pending_create_request(db: Session, sub_task_id: int) -> bool:
    """Check if a SubTask has a pending CREATE approval request."""
    request = (
        db.query(SubTaskUpdateRequest)
        .filter(SubTaskUpdateRequest.sub_task_id == sub_task_id)
        .filter(SubTaskUpdateRequest.request_type == SubTaskUpdateRequestType.create.value)
        .filter(SubTaskUpdateRequest.status == SubTaskUpdateRequestStatus.pending.value)
        .first()
    )
    return request is not None


def _filter_active_sub_tasks(db: Session, sub_tasks: list[SubTask], current_user: User | None = None) -> list[SubTask]:
    """Filter out pending CREATE subtasks for non-admin users."""
    if current_user and current_user.role == "admin":
        return sub_tasks
    
    # For non-admins, filter out subtasks with pending CREATE requests
    pending_create_ids = set()
    for st in sub_tasks:
        if _has_pending_create_request(db, st.id):
            pending_create_ids.add(st.id)
    
    return [st for st in sub_tasks if st.id not in pending_create_ids]


def _serialize_user_reference(user: User | None, fallback_id: int | None):
    if user:
        return {"id": user.id, "name": user.username}
    if fallback_id is not None:
        return {"id": fallback_id, "name": "Unknown"}
    return None


def _serialize_department_reference(user: User | None):
    if not user or not getattr(user, "departments", None):
        return None

    department = sorted(user.departments, key=lambda item: item.id)[0]
    return {"id": department.id, "name": department.name}


def _serialize_department_model(department: Department | None):
    if not department:
        return None

    return {"id": department.id, "name": department.name}


def _serialize_category_model(category: Category | None):
    if not category:
        return None

    return {"id": category.id, "name": category.name}


def _serialize_task_department_reference(task: Task):
    department = _serialize_department_model(getattr(task, "department", None))
    if department:
        return department

    sub_tasks = getattr(task, "sub_tasks", None) or []

    for sub_task in sorted(sub_tasks, key=lambda item: item.id):
        department = _serialize_department_reference(getattr(sub_task, "assignee", None))
        if department:
            return department

    return None


def _serialize_task_category_reference(task: Task):
    return _serialize_category_model(getattr(task, "category", None))


def _resolve_department(db: Session, department_id: int | None) -> Department | None:
    if department_id is None:
        return None

    department = db.query(Department).filter(Department.id == department_id).first()
    if not department:
        raise api_error(
            status_code=404,
            code="DEPARTMENT_NOT_FOUND",
            message="Department not found",
        )

    return department


def _resolve_category(db: Session, category_id: int | None) -> Category | None:
    if category_id is None:
        return None

    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise api_error(
            status_code=404,
            code="CATEGORY_NOT_FOUND",
            message="Category not found",
        )

    return category


def _serialize_sub_task(sub_task: SubTask):
    return {
        "id": sub_task.id,
        "title": sub_task.title,
        "description": sub_task.description,
        "status": sub_task.status,
        "tag": getattr(sub_task, "tag", None),
        "raw_weightage_priority": sub_task.raw_weightage_priority,
        "weightage_priority": sub_task.weightage_priority,
        "subtask_priority": sub_task.subtask_priority,
        "estimated_days": sub_task.estimated_days,
        "estimated_hours": sub_task.estimated_hours,
        "start_date": sub_task.start_date,
        "end_date": sub_task.calculate_end_date() if sub_task.start_date else None,
        "actual_days": sub_task.actual_days,
        "actual_hours": sub_task.actual_hours,
        **build_sub_task_timing_fields(sub_task),
        "created_at": sub_task.created_at,
        "completed_at": sub_task.completed_at,
        "task_id": sub_task.task_id,
        "created_by": _serialize_user_reference(sub_task.creator, sub_task.created_by),
        "assigned_to": _serialize_user_reference(sub_task.assignee, sub_task.assigned_to),
    }


def _serialize_task(task: Task, include_sub_tasks: bool = False, db: Session | None = None, current_user: User | None = None):
    payload = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "non_priority_flag": task.non_priority_flag,
        "status": task.status,
        "estimated_days": task.estimated_days,
        "estimated_hours": task.estimated_hours,
        "start_date": task.start_date,
        "end_date": task.end_date,
        "created_by": _serialize_user_reference(task.creator, task.created_by),
        "department_id": task.department_id,
        "department": _serialize_task_department_reference(task),
        "category": _serialize_task_category_reference(task),
        "version": f"{task.version_major}.{task.version_minor}.{task.version_patch}",
        "parent_task_id": task.parent_task_id,
    }

    if include_sub_tasks:
        sub_tasks = task.sub_tasks or []
        # Filter out pending CREATE subtasks for non-admins
        if db and current_user:
            sub_tasks = _filter_active_sub_tasks(db, sub_tasks, current_user)
        payload["sub_tasks"] = [_serialize_sub_task(sub_task) for sub_task in sub_tasks]

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
    def _normalize_requested_payload(requested_payload):
        if not isinstance(requested_payload, dict):
            return requested_payload

        normalized = dict(requested_payload)
        payload = normalized.get("payload")
        if isinstance(payload, dict):
            payload_copy = dict(payload)
            sub_tasks = payload_copy.get("sub_tasks")
            if isinstance(sub_tasks, list):
                temp_ids = normalized.get("subtask_temporary_ids") or normalized.get("subtask_client_ids")
                for idx, sub_task in enumerate(sub_tasks):
                    if not isinstance(sub_task, dict):
                        continue
                    embedded_id = sub_task.get("temporary_subtask_id")
                    if embedded_id is None and isinstance(temp_ids, list) and idx < len(temp_ids):
                        embedded_id = temp_ids[idx]
                    if embedded_id is None:
                        embedded_id = sub_task.get("client_subtask_id")
                    if embedded_id is not None:
                        sub_task = dict(sub_task)
                        sub_task["temporary_subtask_id"] = embedded_id
                        sub_task.pop("client_subtask_id", None)
                        sub_tasks[idx] = sub_task
                payload_copy["sub_tasks"] = sub_tasks
            normalized["payload"] = payload_copy

        normalized.pop("subtask_temporary_ids", None)
        normalized.pop("subtask_client_ids", None)
        return normalized

    return {
        "id": request.id,
        "requested_by": _serialize_user_reference(request.requester, request.requested_by),
        "status": request.status,
        "requested_payload": _normalize_requested_payload(request.requested_payload),
        "review_comment": request.review_comment,
        "reviewed_by": _serialize_user_reference(request.reviewer, request.reviewed_by),
        "approved_task_id": request.approved_task_id,
        "created_at": request.created_at,
        "reviewed_at": request.reviewed_at,
    }


def _validate_non_admin_task_priority_payload(task: TaskCreate):
    """Allow non-admin priority requests only when every sub-task follows the same mode.

    - non_priority_flag=True: no sub-task may explicitly set priority fields.
    - non_priority_flag=False: either all sub-tasks provide both priority fields or none do.
    """
    if not task.sub_tasks:
        return

    priority_field_set = {"weightage_priority", "subtask_priority"}
    saw_complete_priority = False
    saw_missing_priority = False

    for idx, sub_task in enumerate(task.sub_tasks):
        fields_set = getattr(sub_task, "model_fields_set", set())
        provided_fields = priority_field_set.intersection(fields_set)
        has_weightage = sub_task.weightage_priority is not None
        has_subtask_priority = sub_task.subtask_priority is not None
        has_any_priority = has_weightage or has_subtask_priority
        has_all_priority = has_weightage and has_subtask_priority

        if task.non_priority_flag:
            if has_any_priority:
                raise api_error(
                    status_code=400,
                    code="NON_PRIORITY_TASK_HAS_PRIORITY_FIELDS",
                    message="Non-priority tasks cannot include weightage_priority or subtask_priority",
                    details={"sub_task_index": idx, "restricted_fields": sorted(provided_fields)},
                )
            continue

        if provided_fields and provided_fields != priority_field_set:
            raise api_error(
                status_code=400,
                code="INCOMPLETE_SUBTASK_PRIORITY_FIELDS",
                message="Each sub-task must include both weightage_priority and subtask_priority when using priority review",
                details={"sub_task_index": idx, "provided_fields": sorted(provided_fields)},
            )

        if has_any_priority and not has_all_priority:
            raise api_error(
                status_code=400,
                code="INCOMPLETE_SUBTASK_PRIORITY_FIELDS",
                message="Each sub-task must include both weightage_priority and subtask_priority when using priority review",
                details={
                    "sub_task_index": idx,
                    "provided_fields": sorted(provided_fields),
                    "weightage_priority": sub_task.weightage_priority,
                    "subtask_priority": sub_task.subtask_priority,
                },
            )

        if has_all_priority:
            saw_complete_priority = True
        else:
            saw_missing_priority = True

    if not task.non_priority_flag and saw_complete_priority and saw_missing_priority:
        raise api_error(
            status_code=400,
            code="MIXED_SUBTASK_PRIORITY_REVIEW",
            message="Provide weightage_priority and subtask_priority for every sub-task or for none of them",
        )


def _get_non_admin_task_creation_mode(task: TaskCreate) -> str:
    """Classify the non-admin create path.

    Returns:
    - "direct" when every sub-task has both priority fields populated.
    - "approval" when no sub-task priority values are provided.
    - raises when the payload mixes complete and missing priority data.
    """
    if not task.sub_tasks:
        return "approval"

    saw_complete_priority = False
    saw_missing_priority = False

    for idx, sub_task in enumerate(task.sub_tasks):
        has_weightage = sub_task.weightage_priority is not None
        has_subtask_priority = sub_task.subtask_priority is not None
        has_any_priority = has_weightage or has_subtask_priority
        has_all_priority = has_weightage and has_subtask_priority

        if has_any_priority and not has_all_priority:
            raise api_error(
                status_code=400,
                code="INCOMPLETE_SUBTASK_PRIORITY_FIELDS",
                message="Each sub-task must include both weightage_priority and subtask_priority when using priority review",
                details={
                    "sub_task_index": idx,
                    "weightage_priority": sub_task.weightage_priority,
                    "subtask_priority": sub_task.subtask_priority,
                },
            )

        if has_all_priority:
            saw_complete_priority = True
        else:
            saw_missing_priority = True

    if saw_complete_priority and saw_missing_priority:
        raise api_error(
            status_code=400,
            code="MIXED_SUBTASK_PRIORITY_REVIEW",
            message="Provide weightage_priority and subtask_priority for every sub-task or for none of them",
        )

    return "direct" if saw_complete_priority else "approval"


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

    # Top-level whitelist: only non-priority and sub-task priority-related fields may be overridden
    provided_top_level = getattr(override_task, "model_fields_set", set())
    allowed_top_level = {"sub_tasks", "non_priority_flag"}
    extra_top = provided_top_level.difference(allowed_top_level)
    if extra_top:
        raise api_error(
            status_code=400,
            code="INVALID_OVERRIDE_TOP_LEVEL_FIELDS",
            message="Override may only include sub_tasks and non_priority_flag",
            details={"invalid_fields": sorted(list(extra_top))},
        )

    if override_task.non_priority_flag != original_task.non_priority_flag:
        changes["non_priority_flag"] = {
            "from": original_task.non_priority_flag,
            "to": override_task.non_priority_flag,
        }

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
        stored_temp_ids = getattr(original_task, "_stored_subtask_temporary_ids", None)
        stored_fps = getattr(original_task, "_stored_subtask_fingerprints", None)

        # Prefer client id mapping if present
        if stored_temp_ids and isinstance(stored_temp_ids, list) and len(stored_temp_ids) == len(original_task.sub_tasks):
            for idx, cid in enumerate(stored_temp_ids):
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
            # If override provides a temporary subtask id, try id mapping first
            temporary_id = getattr(override_st, "temporary_subtask_id", None) or (override_st.get("temporary_subtask_id") if isinstance(override_st, dict) else None)
            matched = False
            if temporary_id is not None and f"client:{temporary_id}" in orig_map and orig_map[f"client:{temporary_id}"]:
                orig_idx = orig_map[f"client:{temporary_id}"].pop(0)
                orig_st = original_task.sub_tasks[orig_idx]
                matched = True
            else:
                fp = _fingerprint_from_obj(override_st)
                if fp not in orig_map or not orig_map[fp]:
                    raise api_error(
                        status_code=400,
                        code="UNMATCHED_OVERRIDE_SUBTASK",
                        message="Override sub_task does not match any original sub_task by fingerprint",
                        details={"fingerprint": fp, "temporary_id": temporary_id},
                    )
                orig_idx = orig_map[fp].pop(0)
                orig_st = original_task.sub_tasks[orig_idx]
                matched = True

            # Per-subtask whitelist of allowed override fields
            provided_fields = getattr(override_st, "model_fields_set", set())
            allowed_fields = {"temporary_subtask_id", "weightage_priority", "subtask_priority"}
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
    department = _resolve_department(db, task.department_id)
    category = _resolve_category(db, task.category_id)

    new_task = Task(
        title=task.title,
        description=task.description,
        status=TaskStatus.in_progress.value,
        non_priority_flag=task.non_priority_flag,
        department_id=department.id if department else None,
        category_id=category.id if category else None,
        created_by=creator_id,
    )

    db.add(new_task)
    created_sub_tasks: list[SubTask] = []
    db.flush()

    if task.sub_tasks:
        # Capture original payload weightage values before normalization
        payload_raws = [
            (st.weightage_priority if st.weightage_priority is not None else 0)
            for st in task.sub_tasks
        ]

        if not task.non_priority_flag:
            normalized_priorities = _normalize_weightage_priority_values(
                [sub_task.weightage_priority for sub_task in task.sub_tasks]
            )
            for sub_task, normalized_priority in zip(task.sub_tasks, normalized_priorities):
                sub_task.weightage_priority = normalized_priority

        for idx, sub_task in enumerate(task.sub_tasks):
            print(
                "SUBTASK:",
                sub_task.title,
                "assigned_to=",
                sub_task.assigned_to,
                "assigned_to_username=",
                sub_task.assigned_to_username,
            )
            assigned_user = resolve_assigned_user(
                db=db,
                assigned_to=sub_task.assigned_to,
                assigned_to_username=sub_task.assigned_to_username,
                current_user=current_user,
            )

            effective_non_priority_flag = task.non_priority_flag

            if not effective_non_priority_flag and (
                sub_task.weightage_priority is None or sub_task.subtask_priority is None
            ):
                raise api_error(
                    status_code=400,
                    code="MISSING_PRIORITY_SUBTASK_FIELDS",
                    message="Priority sub-task must include weightage_priority and subtask_priority",
                    details={"title": sub_task.title},
                )

            weightage_priority = 0 if effective_non_priority_flag else sub_task.weightage_priority
            subtask_priority = (
                SubTaskPriority.medium.value
                if effective_non_priority_flag
                else sub_task.subtask_priority.value
            )

            raw_weightage_priority = getattr(sub_task, "raw_weightage_priority", None)
            if raw_weightage_priority is None:
                # Use the original submitted value (payload_raws) rather than the
                # normalized `weightage_priority` so `raw_weightage_priority` stores
                # the incoming payload number.
                raw_weightage_priority = payload_raws[idx] if idx < len(payload_raws) else (weightage_priority or 0)

            new_sub_task = SubTask(
                title=sub_task.title,
                description=sub_task.description,
                status=sub_task.status.value,
                tag="in progress",
                non_priority_flag=task.non_priority_flag,
                raw_weightage_priority=raw_weightage_priority,
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
    if task.category_id is None:
        raise api_error(
            status_code=422,
            code="THERE_SHOULD_BE_CATEGORY_ID",
            message="there should be category_id in payload while creating task",
        )

    _resolve_department(db, task.department_id)
    _resolve_category(db, task.category_id)

    if current_user.role != "admin":
        # Non-admin can create directly when the whole task is non-priority.
        if task.non_priority_flag:
            _validate_non_admin_task_priority_payload(task)
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
                    "non_priority_flag": True,
                },
            )
            db.commit()
            return {
                **_serialize_task(new_task, include_sub_tasks=True, db=db, current_user=current_user),
                "sub_tasks": [_serialize_sub_task(sub_task) for sub_task in created_sub_tasks],
                "sub_tasks_created_count": len(created_sub_tasks),
            }

        _validate_non_admin_task_priority_payload(task)

        if task.sub_tasks:
            for subtask in task.sub_tasks:
                if not subtask.assigned_to and not subtask.assigned_to_username:
                    subtask.assigned_to = current_user.id

        # Store payload with explicit version wrapper and fingerprints
        payload_wrapper = jsonable_encoder(task)
        if isinstance(payload_wrapper, dict):
            payload_wrapper["department_id"] = task.department_id
            payload_wrapper["category_id"] = task.category_id

        def _fingerprint_obj(st):
            if isinstance(st, dict):
                title = st.get("title") or ""
                desc = st.get("description") or ""
                days = st.get("estimated_days") if st.get("estimated_days") is not None else ""
                hours = st.get("estimated_hours") if st.get("estimated_hours") is not None else ""
                assignee = st.get("assigned_to_username") or ""
            else:
                title = st.title or ""
                desc = st.description or ""
                days = st.estimated_days if st.estimated_days is not None else ""
                hours = st.estimated_hours if st.estimated_hours is not None else ""
                assignee = getattr(st, "assigned_to_username", "") or ""
            return f"{str(title).strip().lower()}|{str(desc).strip().lower()}|{str(days)}|{str(hours)}|{str(assignee).strip().lower()}"

        subtask_fps = []
        if getattr(task, "sub_tasks", None):
            # inject server-generated temporary_subtask_id into each sub_task in the stored payload
            if isinstance(payload_wrapper, dict) and "sub_tasks" in payload_wrapper and isinstance(payload_wrapper["sub_tasks"], list):
                for st_dict in payload_wrapper["sub_tasks"]:
                    subtask_id = uuid.uuid4().hex
                    st_dict["temporary_subtask_id"] = subtask_id
                    subtask_fps.append(_fingerprint_obj(st_dict))
            else:
                for st in task.sub_tasks:
                    subtask_fps.append(_fingerprint_obj(st))

        if isinstance(payload_wrapper, dict):
            payload_wrapper = {
                "payload": payload_wrapper,
                "version": getattr(TaskCreate, "__payload_version__", 1),
                "subtask_fingerprints": subtask_fps,
                "department_id": task.department_id,
                "category_id": task.category_id,
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
        if task.department_id is None:
            raise api_error(
                status_code=422,
                code="THERE_SHOULD_BE_DEPARTMENT_ID",
                message="there should be department_id in payload while creating task",
            )
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
        **_serialize_task(new_task, include_sub_tasks=True, db=db, current_user=current_user),
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

    try:
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
            if stored.get("department_id") is not None:
                payload_body["department_id"] = stored["department_id"]
            if stored.get("category_id") is not None:
                payload_body["category_id"] = stored["category_id"]
        else:
            payload_body = stored
            stored_version = 1

        try:
            original_task = TaskCreate(**payload_body)
            # attach stored fingerprints to the TaskCreate instance for later matching
            if isinstance(stored, dict):
                if "subtask_fingerprints" in stored:
                    setattr(original_task, "_stored_subtask_fingerprints", stored.get("subtask_fingerprints"))
            # If temporary ids were embedded in the stored payload sub_tasks, extract them
            stored_temp_ids = None
            if isinstance(payload_body, dict) and payload_body.get("sub_tasks"):
                maybe_ids = [st.get("temporary_subtask_id") if isinstance(st, dict) else None for st in payload_body.get("sub_tasks")]
                if any(maybe_ids):
                    stored_temp_ids = maybe_ids
            # Fallback to separate array key if present (legacy)
            if isinstance(stored, dict) and "subtask_temporary_ids" in stored:
                stored_temp_ids = stored.get("subtask_temporary_ids")
            if stored_temp_ids is not None:
                setattr(original_task, "_stored_subtask_temporary_ids", stored_temp_ids)
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
        task_payload = original_task.model_copy(deep=True)
        task_payload.department_id = original_task.department_id
        task_payload.category_id = original_task.category_id
        if payload.approved_payload:
            override_diff = _validate_approved_payload_safe_override(original_task, payload.approved_payload)
            if payload.approved_payload.non_priority_flag is not None:
                task_payload.non_priority_flag = payload.approved_payload.non_priority_flag

            if payload.approved_payload.sub_tasks is not None and task_payload.sub_tasks is not None:
                approved_sub_tasks = []
                original_temp_ids = []
                stored_temp_ids = getattr(original_task, "_stored_subtask_temporary_ids", None)
                if isinstance(stored_temp_ids, list):
                    original_temp_ids = stored_temp_ids

                original_lookup: dict[str, list[int]] = {}

                def _fingerprint_from_obj(st):
                    title = getattr(st, "title", None) or (st.get("title") if isinstance(st, dict) else "")
                    desc = getattr(st, "description", None) or (st.get("description") if isinstance(st, dict) else "")
                    days = getattr(st, "estimated_days", None) or (st.get("estimated_days") if isinstance(st, dict) else "")
                    hours = getattr(st, "estimated_hours", None) or (st.get("estimated_hours") if isinstance(st, dict) else "")
                    assignee = getattr(st, "assigned_to_username", None) or (st.get("assigned_to_username") if isinstance(st, dict) else "")
                    return f"{str(title).strip().lower()}|{str(desc).strip().lower()}|{str(days)}|{str(hours)}|{str(assignee).strip().lower()}"

                for idx, st in enumerate(original_task.sub_tasks or []):
                    if idx < len(original_temp_ids) and original_temp_ids[idx] is not None:
                        original_lookup.setdefault(f"client:{original_temp_ids[idx]}", []).append(idx)
                    original_lookup.setdefault(_fingerprint_from_obj(st), []).append(idx)

                for override_st in payload.approved_payload.sub_tasks:
                    temporary_id = getattr(override_st, "temporary_subtask_id", None)
                    orig_idx = None
                    if temporary_id is not None and f"client:{temporary_id}" in original_lookup and original_lookup[f"client:{temporary_id}"]:
                        orig_idx = original_lookup[f"client:{temporary_id}"].pop(0)
                    else:
                        fp = _fingerprint_from_obj(override_st)
                        if fp in original_lookup and original_lookup[fp]:
                            orig_idx = original_lookup[fp].pop(0)
                    if orig_idx is None:
                        raise api_error(
                            status_code=400,
                            code="UNMATCHED_OVERRIDE_SUBTASK",
                            message="Override sub_task does not match any original sub_task",
                            details={"temporary_id": temporary_id},
                        )

                    original_st = original_task.sub_tasks[orig_idx]
                    copied_sub_task = original_st.model_copy(
                        update={
                            "weightage_priority": override_st.weightage_priority,
                            "subtask_priority": override_st.subtask_priority,
                        },
                        deep=True,
                    )
                    approved_sub_tasks.append(copied_sub_task)

                task_payload.sub_tasks = approved_sub_tasks

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
                **_serialize_task(new_task, include_sub_tasks=True, db=db, current_user=current_user),
                "sub_tasks": [_serialize_sub_task(st) for st in created_sub_tasks],
            },
        }
        if override_diff:
            audit_details["override_diff"] = override_diff

        audit_details = jsonable_encoder(audit_details)

        log_audit_event(
            db=db,
            action="APPROVE",
            entity_type="task_creation_request",
            entity_id=request.id,
            user_id=current_user.id,
            message="Task creation request approved",
            details=audit_details,
        )

        db.flush()
        db.commit()
        db.refresh(request)
        return _serialize_task_creation_request(request)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
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
    query = db.query(Task).options(
        selectinload(Task.sub_tasks),
        selectinload(Task.department),
        selectinload(Task.category),
        selectinload(Task.creator).selectinload(User.departments),
        selectinload(Task.sub_tasks).selectinload(SubTask.assignee).selectinload(User.departments),
    ).filter(
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

    serialized_items = [_serialize_task(task, include_sub_tasks=True, db=db, current_user=current_user) for task in items]

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


def _apply_task_update(db: Session, task: Task, update_data: dict):
    if "status" in update_data and update_data["status"] is not None:
        if task.status == TaskStatus.complete.value and update_data["status"].value != TaskStatus.complete.value:
            raise api_error(
                status_code=400,
                code="TASK_ALREADY_COMPLETE",
                message="A completed task cannot be reopened",
            )
        update_data["status"] = update_data["status"].value

    if "department_id" in update_data:
        department = _resolve_department(db, update_data["department_id"])
        update_data["department_id"] = department.id if department else None

    if "category_id" in update_data:
        category = _resolve_category(db, update_data["category_id"])
        update_data["category_id"] = category.id if category else None

    for key, value in update_data.items():
        setattr(task, key, value)

    if update_data.get("non_priority_flag") is True:
        db.query(SubTask).filter(SubTask.task_id == task.id).update(
            {
                SubTask.non_priority_flag: True,
                SubTask.weightage_priority: 0,
                SubTask.subtask_priority: SubTaskPriority.medium.value,
            },
            synchronize_session=False,
        )


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
    department_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
):
    query = db.query(Task).options(
        selectinload(Task.department),
        selectinload(Task.category),
        selectinload(Task.sub_tasks).selectinload(SubTask.assignee).selectinload(User.departments),
    )

    if status:
        query = query.filter(Task.status == status)

    if department_id:
        query = query.filter(Task.department_id == department_id)

    if category_id:
        query = query.filter(Task.category_id == category_id)

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(Task.title.ilike(search_pattern), Task.description.ilike(search_pattern))
        )

    print(
        query.statement.compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    total = query.count()
    tasks = (
        query.order_by(Task.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
    valid_statuses = {status.value for status in TaskStatus}
    for task in tasks:
        safe_status = task.status if task.status in valid_statuses else TaskStatus.not_complete.value
        result.append(
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "non_priority_flag": task.non_priority_flag,
                "status": safe_status,
                "estimated_days": task.estimated_days,
                "estimated_hours": task.estimated_hours,
                "start_date": task.start_date,
                "end_date": task.end_date,
                "created_by": _serialize_user_reference(task.creator, task.created_by),
                "department": _serialize_task_department_reference(task),
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
    pending_create_sub_task_ids = (
        db.query(SubTaskUpdateRequest.sub_task_id)
        .filter(
            SubTaskUpdateRequest.request_type == SubTaskUpdateRequestType.create.value,
            SubTaskUpdateRequest.status == SubTaskUpdateRequestStatus.pending.value,
        )
    )

    rejected_create_sub_task_ids = (
        db.query(SubTaskUpdateRequest.sub_task_id)
        .filter(
            SubTaskUpdateRequest.request_type == SubTaskUpdateRequestType.create.value,
            SubTaskUpdateRequest.status == SubTaskUpdateRequestStatus.rejected.value,
        )
    )

    sub_tasks_loader = (
        selectinload(
            Task.sub_tasks.and_(
                ~SubTask.id.in_(pending_create_sub_task_ids),
                ~SubTask.id.in_(rejected_create_sub_task_ids),
            )
        )
        .selectinload(SubTask.assignee)
        .selectinload(User.departments)
    )

    task = (
        db.query(Task)
        .options(
            sub_tasks_loader,
            selectinload(Task.department),
            selectinload(Task.category),
            selectinload(Task.creator).selectinload(User.departments),
        )
        .filter(Task.id == task_id)
        .first()
    )

    if not task:
        raise api_error(status_code=404, code="TASK_NOT_FOUND", message="Task not found")

    ensure_user_can_manage_task(task, current_user)

    return _serialize_task(task, include_sub_tasks=True, db=db, current_user=current_user)


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

    excluded_sub_task_ids = (
        db.query(SubTaskUpdateRequest.sub_task_id)
        .filter(
            SubTaskUpdateRequest.request_type == SubTaskUpdateRequestType.create.value,
            SubTaskUpdateRequest.status.in_([
                SubTaskUpdateRequestStatus.pending.value,
                SubTaskUpdateRequestStatus.rejected.value,
            ]),
        )
    )

    completed_weightage = (
        db.query(func.coalesce(func.sum(SubTask.weightage_priority), 0))
        .filter(SubTask.task_id == task_id)
        .filter(SubTask.status == SubTaskStatus.complete.value)
        .filter(~SubTask.id.in_(excluded_sub_task_ids))
        .scalar()
    )
    
    progress_percentage = round(completed_weightage, 2)

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

    excluded_sub_task_ids = (
        db.query(SubTaskUpdateRequest.sub_task_id)
        .filter(
            SubTaskUpdateRequest.request_type == SubTaskUpdateRequestType.create.value,
            SubTaskUpdateRequest.status.in_([
                SubTaskUpdateRequestStatus.pending.value,
                SubTaskUpdateRequestStatus.rejected.value,
            ]),
        )
    )

    valid_sub_tasks = (
        db.query(SubTask)
        .filter(
            SubTask.task_id == task.id,
            ~SubTask.id.in_(excluded_sub_task_ids),
        )
        .all()
    )

    total_estimated_hours, total_actual_hours, total_expected_hours = (
        calculate_task_behind_hours_from_sub_tasks(valid_sub_tasks)
    )

    sub_tasks_timeline = []

    for sub_task in task.sub_tasks:
        timing = build_sub_task_timing_fields(sub_task)

        sub_tasks_timeline.append(
            {
                "sub_task_id": sub_task.id,
                "title": sub_task.title,
                "status": sub_task.status,
                "priority": sub_task.weightage_priority,
                "estimated_hours": timing["total_estimated_hours"],
                "elapsed_hours": timing["elapsed_hours"],
                "expected_completion_hours": timing["expected_completion_hours"],
                "actual_hours": timing["total_actual_hours"],
                "start_date": sub_task.start_date,
                "end_date": sub_task.end_date,
                "assigned_to": _serialize_user_reference(sub_task.assignee, sub_task.assigned_to)
            }
        )

    if total_estimated_hours > 0:
        estimated_percentage = 100.0
        actual_percentage = round((total_actual_hours / total_estimated_hours) * 100, 2)
        behind_percentage = round((total_expected_hours / total_estimated_hours) * 100, 2)
    else:
        estimated_percentage = 0.0
        actual_percentage = 0.0
        behind_percentage = 0.0

    # Determine status based on actual vs estimated hours
    if total_actual_hours > total_estimated_hours:
        status = "behind"
    elif total_actual_hours == total_estimated_hours:
        status = "on time"
    else:
        status = "early"

    # Calculate expected_days from expected_hours (non-decimal)
    expected_days = int(total_expected_hours / 24) if total_expected_hours > 0 else 0

    return {
        "task_id": task.id,
        "task_title": task.title,
        "start_date": task.start_date,
        "end_date": task.end_date,
        "total_estimated_hours": total_estimated_hours,
        "total_actual_hours": total_actual_hours,
        "total_expected_hours": total_expected_hours,
        "expected_days": expected_days,
        "status": status,
        "bars": [
            {
                "key": "estimated",
                "label": "How much time it will take",
                "hours": total_estimated_hours,
                "percentage": estimated_percentage,
            },
            {
                "key": "actual",
                "label": "How much time user took",
                "hours": total_actual_hours,
                "percentage": actual_percentage,
            },
            {
                "key": "expected",
                "label": "How much time it should have taken",
                "hours": total_expected_hours,
                "percentage": behind_percentage,
            },
        ]
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

    normalized_priorities = _normalize_weightage_priority_values(
        [item.weightage_priority for item in payload.items]
    )

    priority_map = {
        item.sub_task_id: normalized_priority
        for item, normalized_priority in zip(payload.items, normalized_priorities)
    }
    raw_priority_map = {
        item.sub_task_id: item.weightage_priority or 0 for item in payload.items
    }
    for sub_task in task.sub_tasks:
        sub_task.weightage_priority = priority_map[sub_task.id]
        sub_task.raw_weightage_priority = raw_priority_map[sub_task.id]

    db.flush()

    log_audit_event(
        db=db,
        action="UPDATE",
        entity_type="task",
        entity_id=task.id,
        user_id=current_user.id,
        message="Sub-task priorities updated in bulk",
        details={"sub_task_count": len(payload.items), "total_priority": sum(normalized_priorities)},
    )
    db.commit()

    return {
        "task_id": task.id,
        "total_priority": sum(normalized_priorities),
        "items": [
            item.model_copy(update={"weightage_priority": normalized_priority})
            for item, normalized_priority in zip(payload.items, normalized_priorities)
        ],
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

    _resolve_department(db, update_data.get("department_id"))

    effective_non_priority_flag = update_data.get("non_priority_flag", task.non_priority_flag)

    if current_user.role != "admin":
        if effective_non_priority_flag:
            _apply_task_update(db, task, update_data)
            log_audit_event(
                db=db,
                action="UPDATE",
                entity_type="task",
                entity_id=task.id,
                user_id=current_user.id,
                message="Task updated",
                details={"updated_fields": list(update_data.keys()), "non_priority_flag": True},
            )
            db.commit()
            db.refresh(task)
            return _serialize_task(task)

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

    _apply_task_update(db, task, update_data)

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
    payload: TaskVersionBumpRequest,
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

    if not payload.sub_tasks:
        raise api_error(
            status_code=422,
            code="SUBTASKS_REQUIRED",
            message="Sub-tasks are required for revision",
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

    revision_sub_tasks = payload.sub_tasks

    revision_payload = TaskCreate(
        title=task.title,
        description=task.description,
        non_priority_flag=task.non_priority_flag,
        sub_tasks=revision_sub_tasks,
        department_id=task.department_id,
        category_id=task.category_id,
    )

    new_task, created_sub_tasks = _create_task_from_payload(
        db,
        revision_payload,
        creator_id=current_user.id,
        current_user=current_user,
    )

    new_task.status = TaskStatus.not_complete.value
    new_task.version_major = next_major
    new_task.version_minor = next_minor
    new_task.version_patch = next_patch
    new_task.parent_task_id = task.id

    recalculate_task_estimated_time(db, new_task.id)

    db.commit()
    db.refresh(new_task)
    for sub_task in created_sub_tasks:
        db.refresh(sub_task)


    log_audit_event(
        db=db,
        action="REVISE",
        entity_type="task",
        entity_id=new_task.id,
        user_id=current_user.id,
        message="New task version created",
        details={
            "previous_task_id": task.id,
            "new_version": f"{next_major}.{next_minor}.{next_patch}",
            "bump_type": payload.bump_type,
            "sub_tasks_count": len(created_sub_tasks),
        },
    )
    db.commit()


    return _serialize_task(new_task)


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

    sub_task_ids = [sub_task.id for sub_task in db.query(SubTask.id).filter(SubTask.task_id == task.id).all()]
    if sub_task_ids:
        db.query(SubTaskUpdateRequest).filter(
            SubTaskUpdateRequest.sub_task_id.in_(sub_task_ids)
        ).delete(synchronize_session=False)

    db.query(SubTask).filter(SubTask.task_id == task.id).delete(synchronize_session=False)
    db.query(TaskUpdateRequest).filter(TaskUpdateRequest.task_id == task.id).delete(synchronize_session=False)
    db.delete(task)
    db.commit()

    return {"message": "Task deleted successfully"}
