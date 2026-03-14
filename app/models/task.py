from datetime import datetime
import enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class TaskStatus(str, enum.Enum):
    complete = "complete"
    not_complete = "not complete"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime)
    status = Column(String, default="not complete")
    estimated_days = Column(Integer, default=0)
    estimated_hours = Column(Integer, default=0)

    version = Column(Integer, default=1, nullable=False)
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"))
    assigned_to = Column(Integer, ForeignKey("users.id"))

    creator = relationship("User", foreign_keys=[created_by])
    assignee = relationship("User", foreign_keys=[assigned_to])
    parent_task = relationship("Task", foreign_keys=[parent_task_id], remote_side="Task.id")
