from sqlalchemy import CheckConstraint, Column, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.department import user_departments


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("password <> ''", name="ck_users_password_not_empty"),)

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String, nullable=False)
    role = Column(String, default="user")
    departments = relationship(
        "Department",
        secondary=user_departments,
        back_populates="users",
    )
