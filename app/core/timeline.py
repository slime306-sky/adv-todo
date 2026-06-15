from datetime import datetime, timezone

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


def calculate_expected_completion_hours(sub_task: SubTask, elapsed_hours: float) -> float:
    estimated_hours = to_total_hours(sub_task.estimated_days, sub_task.estimated_hours)
    if sub_task.status == SubTaskStatus.complete.value:
        return round(estimated_hours, 2)
    return round(estimated_hours + elapsed_hours, 2)


def build_sub_task_timing_fields(sub_task: SubTask, reference_time: datetime | None = None) -> dict:
    elapsed_hours = calculate_elapsed_hours(sub_task, reference_time)
    expected_completion_hours = calculate_expected_completion_hours(sub_task, elapsed_hours)
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
