from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: int | None = None
    message: str
    details: dict | None = None
    user_id: int | None = None
    created_at: datetime

    class Config:
        orm_mode = True


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
