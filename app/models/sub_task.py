import enum
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class SubTaskStatus(str, enum.Enum):
    complete = "complete"
    not_complete = "not complete"


class SubTaskPriority(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class SubTask(Base):
    __tablename__ = "sub_tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    status = Column(String, default=SubTaskStatus.not_complete.value)
    weightage_priority = Column(Integer, default=0)
    subtask_priority = Column(String, default=SubTaskPriority.medium.value)
    estimated_days = Column(Integer, default=0)
    estimated_hours = Column(Integer, default=0)
    actual_days = Column(Integer, default=0)
    actual_hours = Column(Integer, default=0)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

    task = relationship("Task", backref="sub_tasks")
    creator = relationship("User", foreign_keys=[created_by])
    assignee = relationship("User", foreign_keys=[assigned_to])

    def calculate_end_date(self):
        """Calculate end_date based on start_date, estimated_days, and estimated_hours."""
        if self.start_date is None:
            return None
        return self.start_date + timedelta(days=self.estimated_days, hours=self.estimated_hours)
