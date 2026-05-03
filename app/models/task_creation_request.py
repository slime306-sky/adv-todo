from datetime import datetime

import enum

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class TaskCreationRequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TaskCreationRequest(Base):
    __tablename__ = "task_creation_requests"

    id = Column(Integer, primary_key=True, index=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, default=TaskCreationRequestStatus.pending.value, nullable=False, index=True)
    requested_payload = Column(JSON, nullable=False)
    review_comment = Column(String, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    approved_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)

    requester = relationship("User", foreign_keys=[requested_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    approved_task = relationship("Task", foreign_keys=[approved_task_id])