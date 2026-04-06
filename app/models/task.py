import enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class TaskStatus(str, enum.Enum):
    complete = "complete"
    not_complete = "not complete"
    in_progress = "in progress"
    blocked = "blocked"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    status = Column(String, default=TaskStatus.not_complete.value)
    estimated_days = Column(Integer, default=0)
    estimated_hours = Column(Integer, default=0)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)

    version_major = Column(Integer, default=1, nullable=False)
    version_minor = Column(Integer, default=0, nullable=False)
    version_patch = Column(Integer, default=0, nullable=False)
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"))

    creator = relationship("User", foreign_keys=[created_by])
    parent_task = relationship("Task", foreign_keys=[parent_task_id], remote_side="Task.id")

    @property
    def version(self) -> str:
        return f"{self.version_major}.{self.version_minor}.{self.version_patch}"
