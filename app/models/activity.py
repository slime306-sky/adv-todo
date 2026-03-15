<<<<<<< HEAD
from sqlalchemy import Column, Date, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    date = Column(Date)
    status = Column(String, default="not complete")

    sub_task_id = Column(Integer, ForeignKey("sub_tasks.id"))
    created_by = Column(Integer, ForeignKey("users.id"))

    sub_task = relationship("SubTask", backref="activities")
    creator = relationship("User")
=======
from sqlalchemy import Column, Date, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    date = Column(Date)
    status = Column(String, default="not complete")

    sub_task_id = Column(Integer, ForeignKey("sub_tasks.id"))
    created_by = Column(Integer, ForeignKey("users.id"))

    sub_task = relationship("SubTask", backref="activities")
    creator = relationship("User")
>>>>>>> 9c962f1627ff7435b1f0ba63448f07959fba9ec1
