import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./test.db")

# Render provides postgres:// URLs but SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    connect_args = {"sslmode": "require"}

engine_kwargs = {
    "connect_args": connect_args,
    "pool_pre_ping": True,
}

if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs["pool_recycle"] = int(os.environ.get("DB_POOL_RECYCLE_SECONDS", "300"))

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()
