import enum
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class SubTaskUpdateRequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class SubTaskUpdateRequest(Base):
    __tablename__ = "sub_task_update_requests"

    id = Column(Integer, primary_key=True, index=True)
    sub_task_id = Column(Integer, ForeignKey("sub_tasks.id"), nullable=False, index=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, default=SubTaskUpdateRequestStatus.pending.value, nullable=False, index=True)
    requested_changes = Column(JSON, nullable=False)
    review_comment = Column(String, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)

    sub_task = relationship("SubTask")
    requester = relationship("User", foreign_keys=[requested_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
