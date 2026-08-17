from datetime import datetime, timedelta, timezone

from app.models.sub_task import SubTask, SubTaskStatus


def to_total_hours(days: int | None, hours: int | None) -> float:
    return float(((days or 0) * 24) + (hours or 0))


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def calculate_elapsed_hours(sub_task: SubTask, reference_time: datetime | None = None) -> float:
    start_date = _normalize_datetime(sub_task.start_date)
    if start_date is None:
        return 0.0

    if sub_task.status == SubTaskStatus.complete.value and sub_task.completed_at:
        end = _normalize_datetime(sub_task.completed_at)
    else:
        end = _normalize_datetime(reference_time) or datetime.utcnow()

    if end is None:
        return 0.0

    elapsed_seconds = (end - start_date).total_seconds()
    return round(max(0.0, elapsed_seconds / 3600), 2)


def calculate_expected_completion_hours(
    sub_task: SubTask,
    elapsed_hours: float | None = None,
    reference_time: datetime | None = None,
) -> float:
    # Keep this helper for compatibility while delegating to schedule-based progress.
    return calculate_sub_task_expected_progress_hours(sub_task, reference_time)


def calculate_sub_task_expected_progress_hours(
    sub_task: SubTask,
    reference_time: datetime | None = None,
) -> float:
    """Return schedule-based expected progress hours for a sub-task."""
    estimated_hours = to_total_hours(sub_task.estimated_days, sub_task.estimated_hours)
    if estimated_hours <= 0:
        return 0.0

    start_date = _normalize_datetime(sub_task.start_date)
    if start_date is None:
        return 0.0

    end_date = _normalize_datetime(sub_task.end_date)
    if end_date is None or end_date <= start_date:
        end_date = start_date + timedelta(hours=estimated_hours)

    if sub_task.status == SubTaskStatus.complete.value and sub_task.completed_at:
        now = _normalize_datetime(sub_task.completed_at)
    else:
        now = _normalize_datetime(reference_time) or datetime.utcnow()

    if now <= start_date:
        return 0.0

    scheduled_seconds = (end_date - start_date).total_seconds()
    if scheduled_seconds <= 0:
        return round(estimated_hours if now > end_date else 0.0, 2)

    if now >= end_date:
        return round(estimated_hours, 2)

    elapsed_seconds = (now - start_date).total_seconds()
    progress_ratio = max(0.0, min(1.0, elapsed_seconds / scheduled_seconds))
    return round(estimated_hours * progress_ratio, 2)


def calculate_task_behind_hours_from_sub_tasks(
    sub_tasks: list[SubTask],
    reference_time: datetime | None = None,
) -> tuple[float, float, float]:
    """Return total estimated, actual, and behind-schedule hours for a task from subtasks."""
    total_estimated_hours = 0.0
    total_actual_hours = 0.0
    expected_progress_hours = 0.0

    for sub_task in sub_tasks:
        total_estimated_hours += to_total_hours(sub_task.estimated_days, sub_task.estimated_hours)
        total_actual_hours += to_total_hours(sub_task.actual_days, sub_task.actual_hours)
        expected_progress_hours += calculate_sub_task_expected_progress_hours(
            sub_task,
            reference_time,
        )

    behind_hours = max(expected_progress_hours - total_actual_hours, 0.0)
    return (
        round(total_estimated_hours, 2),
        round(total_actual_hours, 2),
        round(behind_hours, 2),
    )


def build_sub_task_timing_fields(sub_task: SubTask, reference_time: datetime | None = None) -> dict:
    elapsed_hours = calculate_elapsed_hours(sub_task, reference_time)
    expected_completion_hours = calculate_expected_completion_hours(
        sub_task,
        elapsed_hours,
        reference_time,
    )
    return {
        "total_estimated_hours": round(
            to_total_hours(sub_task.estimated_days, sub_task.estimated_hours), 2
        ),
        "total_actual_hours": round(
            to_total_hours(sub_task.actual_days, sub_task.actual_hours), 2
        ),
        "elapsed_hours": elapsed_hours,
        "expected_completion_hours": expected_completion_hours,
    }
