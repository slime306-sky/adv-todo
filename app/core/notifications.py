import logging
from typing import Any

from sqlalchemy.orm import Session

from kathayati import notify

from app.models.user import User
from app.models.task import Task
from app.models.sub_task import SubTask

logger = logging.getLogger(__name__)

CHANNEL = "resend"


def _user_data(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email or "",
    }


def _send(
    db: Session,
    *,
    template: str,
    recipient: User,
    data: dict[str, Any],
) -> None:
    """Queue one email in the current SQLAlchemy transaction."""
    if not recipient.email:
        logger.warning(
            "Notification skipped: user %s has no email",
            recipient.id,
        )
        return

    notify(
        template=template,
        channel=CHANNEL,
        recipient=recipient.email,
        data=data,
        connection=db.connection(),
    )



def notify_admins(
    db: Session,
    *,
    template: str,
    data: dict[str, Any],
) -> None:
    """Notify every admin with an email address."""
    admins = (
        db.query(User)
        .filter(User.role == "admin")
        .all()
    )

    for admin in admins:
        try:
            _send(
                db,
                template=template,
                recipient=admin,
                data={
                    **data,
                    "recipient": _user_data(admin),
                },
            )
        except Exception:
            # Do not let one admin's queue failure stop other admins.
            # The caller should still be aware that a queue error occurred.
            logger.exception(
                "Failed to queue %s for admin %s",
                template,
                admin.id,
            )
            raise


def notify_user(
    db: Session,
    *,
    user: User | None,
    template: str,
    data: dict[str, Any],
) -> None:
    if user is None or not user.email:
        logger.warning(
            "Notification %s skipped: recipient missing or has no email",
            template,
        )
        return

    _send(
        db,
        template=template,
        recipient=user,
        data={
            **data,
            "recipient": _user_data(user),
        },
    )

def notify_subtask_assigned(
    db: Session,
    sub_task: SubTask,
    assigned_by: User,
) -> None:
    recipient = (
        db.query(User)
        .filter(User.id == sub_task.assigned_to)
        .first()
    )

    if not recipient:
        logger.warning(
            "Subtask assignment notification skipped: "
            "recipient not found for subtask %s",
            sub_task.id,
        )
        return

    task = (
        db.query(Task)
        .filter(Task.id == sub_task.task_id)
        .first()
    )

    if not task:
        logger.warning(
            "Subtask assignment notification skipped: "
            "task not found for subtask %s",
            sub_task.id,
        )
        return

    notify_user(
        db,
        user=recipient,
        template="subtask-assigned",
        data={
            "assigned_by": _user_data(assigned_by),
            "task": {
                "id": task.id,
                "title": task.title,
            },
            "subtask": {
                "id": sub_task.id,
                "title": sub_task.title,
                "description": sub_task.description or "",
            },
        },
    )

def notify_task_requested(
    db: Session,
    *,
    request_id: int,
    task_title: str,
    requested_by: User,
) -> None:
    notify_admins(
        db,
        template="task-requested",
        data={
            "request": {
                "id": request_id,
                "title": task_title,
            },
            "requested_by": _user_data(requested_by),
        },
    )


def notify_task_decision(
    db: Session,
    *,
    request_id: int,
    task_title: str,
    requested_by: User | None,
    approved: bool,
    reviewed_by: User,
    comment: str | None,
    task_id: int | None = None,
    subtasks: list[dict] | None = None,
) -> None:
    template = (
        "task-request-approved"
        if approved
        else "task-request-rejected"
    )

    notify_user(
        db,
        user=requested_by,
        template=template,
        data={
            "request": {"id": request_id},
            "task": {
                "id": task_id,
                "title": task_title,
            },
            "approved": approved,
            "reviewed_by": _user_data(reviewed_by),
            "comment": comment or "No comment provided.",
            "subtasks": subtasks or [],
        },
    )


def notify_activity_logged(
    db: Session,
    *,
    activity_title: str,
    task: Task,
    subtask: SubTask,
    created_by: User,
) -> None:
    notify_admins(
        db,
        template="activity-logged",
        data={
            "activity": {"title": activity_title},
            "task": {
                "id": task.id,
                "title": task.title,
            },
            "subtask": {
                "id": subtask.id,
                "title": subtask.title,
            },
            "created_by": _user_data(created_by),
        },
    )


def notify_task_assigned(
    db: Session,
    *,
    task: Task,
    assigned_to: User,
    assigned_by: User,
    subtasks: list[SubTask],
) -> None:
    notify_user(
        db,
        user=assigned_to,
        template="task-assigned",
        data={
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description or "",
            },
            "assigned_by": _user_data(assigned_by),
            "subtasks": [
                {
                    "id": subtask.id,
                    "title": subtask.title,
                    "description": subtask.description or "",
                    "estimated_days": subtask.estimated_days or 0,
                    "estimated_hours": subtask.estimated_hours or 0,
                }
                for subtask in subtasks
            ],
        },
    )


def notify_subtask_completed(
    db: Session,
    *,
    task: Task,
    subtask: SubTask,
    completed_by: User,
) -> None:
    notify_admins(
        db,
        template="subtask-completed",
        data={
            "task": {"id": task.id, "title": task.title},
            "subtask": {"id": subtask.id, "title": subtask.title},
            "completed_by": _user_data(completed_by),
        },
    )


def notify_task_completed(
    db: Session,
    *,
    task: Task,
    completed_by: User,
) -> None:
    # Notify admins and the task creator, without sending the same
    # notification twice when the creator is also an admin.
    recipients = {
        admin.id: admin
        for admin in db.query(User)
        .filter(User.role == "admin")
        .all()
    }

    creator = (
        db.query(User)
        .filter(User.id == task.created_by)
        .first()
    )
    if creator:
        recipients[creator.id] = creator

    for recipient in recipients.values():
        notify_user(
            db,
            user=recipient,
            template="task-completed",
            data={
                "task": {
                    "id": task.id,
                    "title": task.title,
                },
                "completed_by": _user_data(completed_by),
            },
        )