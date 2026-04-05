import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class SubTaskStatus(str, enum.Enum):
    complete = "complete"
    not_complete = "not complete"


class SubTask(Base):
    __tablename__ = "sub_tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    status = Column(String, default=SubTaskStatus.not_complete.value)
    priority = Column(Integer, default=0)
    estimated_days = Column(Integer, default=0)
    estimated_hours = Column(Integer, default=0)
    actual_days = Column(Integer, default=0)
    actual_hours = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

    task = relationship("Task", backref="sub_tasks")
    creator = relationship("User")
    assignee = relationship("User", foreign_keys=[assigned_to])
