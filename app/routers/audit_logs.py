from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogListResponse

router = APIRouter(tags=["audit-logs"])


@router.get("/audit-logs", response_model=AuditLogListResponse)
def get_audit_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    query = db.query(AuditLog)

    if current_user.role != "admin":
        query = query.filter(AuditLog.user_id == current_user.id)
    elif user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)

    if action:
        query = query.filter(AuditLog.action == action)

    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)

    if entity_id is not None:
        query = query.filter(AuditLog.entity_id == entity_id)

    if start_date:
        query = query.filter(AuditLog.created_at >= start_date)

    if end_date:
        query = query.filter(AuditLog.created_at <= end_date)

    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                AuditLog.message.ilike(search_pattern),
                AuditLog.action.ilike(search_pattern),
                AuditLog.entity_type.ilike(search_pattern),
            )
        )

    total = query.count()
    items = (
        query.order_by(AuditLog.id.desc())
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
