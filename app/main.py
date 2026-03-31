import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.database import Base, SessionLocal, engine
from app.core.errors import (
	http_exception_handler,
	unhandled_exception_handler,
	validation_exception_handler,
)
from app.core.security import is_supported_password_hash
from app.models.user import User
from app.routers import activities, audit_logs, auth, dashboard, sub_tasks, tasks, users

Base.metadata.create_all(bind=engine)


def _ensure_sqlite_tasks_columns():
    if not engine.url.drivername.startswith("sqlite"):
        return

    with engine.begin() as connection:
        existing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(tasks)"))
        }

        if "version" not in existing_columns:
            connection.execute(
                text("ALTER TABLE tasks ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            )

        if "parent_task_id" not in existing_columns:
            connection.execute(
                text("ALTER TABLE tasks ADD COLUMN parent_task_id INTEGER")
            )


def _repair_legacy_sqlite_sub_tasks_table():
    if not engine.url.drivername.startswith("sqlite"):
        return

    with engine.begin() as connection:
        table_exists = connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'sub_tasks'"
            )
        ).first()

        if not table_exists:
            return

        table_info = list(connection.execute(text("PRAGMA table_info(sub_tasks)")))
        columns = {row[1]: row for row in table_info}
        activity_column = columns.get("activity_id")

        # Legacy schema had sub_tasks.activity_id as NOT NULL, which current model no longer uses.
        if not activity_column or activity_column[3] == 0:
            return

        connection.execute(text("PRAGMA foreign_keys = OFF"))
        try:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS sub_tasks_new (
                        id INTEGER NOT NULL,
                        title VARCHAR NOT NULL,
                        description VARCHAR,
                        status VARCHAR,
                        estimated_days INTEGER,
                        estimated_hours INTEGER,
                        created_at DATETIME,
                        task_id INTEGER NOT NULL,
                        created_by INTEGER NOT NULL,
                        PRIMARY KEY (id),
                        FOREIGN KEY(task_id) REFERENCES tasks (id),
                        FOREIGN KEY(created_by) REFERENCES users (id)
                    )
                    """
                )
            )

            connection.execute(
                text(
                    """
                    INSERT INTO sub_tasks_new (
                        id,
                        title,
                        description,
                        status,
                        estimated_days,
                        estimated_hours,
                        created_at,
                        task_id,
                        created_by
                    )
                    SELECT
                        id,
                        title,
                        description,
                        COALESCE(status, 'not complete'),
                        COALESCE(estimated_days, 0),
                        COALESCE(estimated_hours, 0),
                        created_at,
                        task_id,
                        created_by
                    FROM sub_tasks
                    """
                )
            )

            connection.execute(text("DROP TABLE sub_tasks"))
            connection.execute(text("ALTER TABLE sub_tasks_new RENAME TO sub_tasks"))
        finally:
            connection.execute(text("PRAGMA foreign_keys = ON"))


_ensure_sqlite_tasks_columns()
_repair_legacy_sqlite_sub_tasks_table()

app = FastAPI()


@app.on_event("startup")
def log_invalid_password_hash_count():
    db = SessionLocal()
    try:
        invalid_count = sum(
            1
            for password in db.query(User.password).all()
            if not is_supported_password_hash(password[0])
        )
        if invalid_count > 0:
            print(
                f"[startup-warning] Found {invalid_count} users with invalid password hashes. "
                "Run POST /users/remediate-passwords"
            )
    finally:
        db.close()

# CORS â€” update ALLOWED_ORIGINS env var in Render to restrict to your frontend URL
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if allowed_origins == [""]:
    allowed_origins = [
        "http://localhost:3000",
    ]


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(users.router)
app.include_router(activities.router)
app.include_router(sub_tasks.router)
app.include_router(audit_logs.router)
app.include_router(dashboard.router)
