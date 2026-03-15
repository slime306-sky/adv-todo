from sqlalchemy import CheckConstraint, Column, Integer, String

from app.core.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("password <> ''", name="ck_users_password_not_empty"),)

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String, nullable=False)
    role = Column(String, default="user")
