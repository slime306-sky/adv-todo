<<<<<<< HEAD
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_audit_event(
    db: Session,
    action: str,
    entity_type: str,
    message: str,
    user_id: int | None = None,
    entity_id: int | None = None,
    details: dict | None = None,
):
    audit_log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
        details=details,
        user_id=user_id,
    )
    db.add(audit_log)
=======
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_audit_event(
    db: Session,
    action: str,
    entity_type: str,
    message: str,
    user_id: int | None = None,
    entity_id: int | None = None,
    details: dict | None = None,
):
    audit_log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
        details=details,
        user_id=user_id,
    )
    db.add(audit_log)
>>>>>>> 9c962f1627ff7435b1f0ba63448f07959fba9ec1
