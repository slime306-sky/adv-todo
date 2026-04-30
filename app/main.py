import os
import time
import uuid
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.database import Base, SessionLocal, engine
from app.core.errors import (
	http_exception_handler,
	unhandled_exception_handler,
	validation_exception_handler,
)
from app.core.security import is_supported_password_hash
from app.models.user import User
from app.routers import activities, audit_logs, auth, dashboard, departments, sub_tasks, tasks, users

DB_INIT_MAX_RETRIES = int(os.environ.get("DB_INIT_MAX_RETRIES", "5"))
DB_INIT_RETRY_DELAY_SECONDS = float(os.environ.get("DB_INIT_RETRY_DELAY_SECONDS", "2"))


def _ensure_sqlite_tasks_columns():
    with engine.begin() as connection:
        if engine.url.drivername.startswith("sqlite"):
            existing_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(tasks)"))
            }

            if "version_major" not in existing_columns:
                connection.execute(
                    text("ALTER TABLE tasks ADD COLUMN version_major INTEGER NOT NULL DEFAULT 1")
                )

            if "version_minor" not in existing_columns:
                connection.execute(
                    text("ALTER TABLE tasks ADD COLUMN version_minor INTEGER NOT NULL DEFAULT 0")
                )

            if "version_patch" not in existing_columns:
                connection.execute(
                    text("ALTER TABLE tasks ADD COLUMN version_patch INTEGER NOT NULL DEFAULT 0")
                )

            if "parent_task_id" not in existing_columns:
                connection.execute(
                    text("ALTER TABLE tasks ADD COLUMN parent_task_id INTEGER")
                )

            if "start_date" not in existing_columns:
                connection.execute(
                    text("ALTER TABLE tasks ADD COLUMN start_date DATETIME")
                )

            if "end_date" not in existing_columns:
                connection.execute(
                    text("ALTER TABLE tasks ADD COLUMN end_date DATETIME")
                )
            return

        # PostgreSQL and other backends that support IF NOT EXISTS.
        connection.execute(
            text(
                "ALTER TABLE tasks "
                "ADD COLUMN IF NOT EXISTS version_major INTEGER NOT NULL DEFAULT 1"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE tasks "
                "ADD COLUMN IF NOT EXISTS version_minor INTEGER NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE tasks "
                "ADD COLUMN IF NOT EXISTS version_patch INTEGER NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_task_id INTEGER")
        )
        connection.execute(
            text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_date TIMESTAMP")
        )
        connection.execute(
            text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS end_date TIMESTAMP")
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
                        weightage_priority INTEGER NOT NULL DEFAULT 0,
                        subtask_priority VARCHAR NOT NULL DEFAULT 'medium',
                        estimated_days INTEGER,
                        estimated_hours INTEGER,
                        actual_days INTEGER NOT NULL DEFAULT 0,
                        actual_hours INTEGER NOT NULL DEFAULT 0,
                        start_date DATETIME,
                        end_date DATETIME,
                        created_at DATETIME,
                        completed_at DATETIME,
                        task_id INTEGER NOT NULL,
                        created_by INTEGER NOT NULL,
                        assigned_to INTEGER,
                        PRIMARY KEY (id),
                        FOREIGN KEY(task_id) REFERENCES tasks (id),
                        FOREIGN KEY(created_by) REFERENCES users (id),
                        FOREIGN KEY(assigned_to) REFERENCES users (id)
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
                        weightage_priority,
                        subtask_priority,
                        estimated_days,
                        estimated_hours,
                        actual_days,
                        actual_hours,
                        start_date,
                        end_date,
                        created_at,
                        completed_at,
                        task_id,
                        created_by,
                        assigned_to
                    )
                    SELECT
                        id,
                        title,
                        description,
                        COALESCE(status, 'not complete'),
                        0,
                        'medium',
                        COALESCE(estimated_days, 0),
                        COALESCE(estimated_hours, 0),
                        0,
                        0,
                        created_at,
                        NULL,
                        created_at,
                        NULL,
                        task_id,
                        created_by,
                        created_by
                    FROM sub_tasks
                    """
                )
            )

            connection.execute(text("DROP TABLE sub_tasks"))
            connection.execute(text("ALTER TABLE sub_tasks_new RENAME TO sub_tasks"))
        finally:
            connection.execute(text("PRAGMA foreign_keys = ON"))


def _ensure_sqlite_sub_tasks_timeline_columns():
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

        existing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(sub_tasks)"))
        }

        if "weightage_priority" not in existing_columns:
            connection.execute(
                text("ALTER TABLE sub_tasks ADD COLUMN weightage_priority INTEGER NOT NULL DEFAULT 0")
            )

        if "subtask_priority" not in existing_columns:
            connection.execute(
                text("ALTER TABLE sub_tasks ADD COLUMN subtask_priority VARCHAR NOT NULL DEFAULT 'medium'")
            )

        if "actual_days" not in existing_columns:
            connection.execute(
                text("ALTER TABLE sub_tasks ADD COLUMN actual_days INTEGER NOT NULL DEFAULT 0")
            )

        if "actual_hours" not in existing_columns:
            connection.execute(
                text("ALTER TABLE sub_tasks ADD COLUMN actual_hours INTEGER NOT NULL DEFAULT 0")
            )

        if "completed_at" not in existing_columns:
            connection.execute(text("ALTER TABLE sub_tasks ADD COLUMN completed_at DATETIME"))

        if "start_date" not in existing_columns:
            connection.execute(text("ALTER TABLE sub_tasks ADD COLUMN start_date DATETIME"))

        if "end_date" not in existing_columns:
            connection.execute(text("ALTER TABLE sub_tasks ADD COLUMN end_date DATETIME"))

        connection.execute(
            text("UPDATE sub_tasks SET start_date = created_at WHERE start_date IS NULL")
        )


def _ensure_sub_tasks_assigned_to_column():
    with engine.begin() as connection:
        if engine.url.drivername.startswith("sqlite"):
            table_exists = connection.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'sub_tasks'"
                )
            ).first()

            if not table_exists:
                return

            existing_columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(sub_tasks)"))
            }

            if "assigned_to" not in existing_columns:
                connection.execute(
                    text("ALTER TABLE sub_tasks ADD COLUMN assigned_to INTEGER")
                )

            if "start_date" not in existing_columns:
                connection.execute(
                    text("ALTER TABLE sub_tasks ADD COLUMN start_date DATETIME")
                )

            connection.execute(
                text("UPDATE sub_tasks SET start_date = created_at WHERE start_date IS NULL")
            )
            return

        # PostgreSQL and other backends that support IF NOT EXISTS.
        connection.execute(
            text("ALTER TABLE sub_tasks ADD COLUMN IF NOT EXISTS assigned_to INTEGER")
        )
        connection.execute(
            text("ALTER TABLE sub_tasks ADD COLUMN IF NOT EXISTS start_date TIMESTAMP")
        )
        connection.execute(
            text("UPDATE sub_tasks SET start_date = created_at WHERE start_date IS NULL")
        )


def _ensure_audit_logs_cascade_delete():
    """Ensure audit_logs foreign key has ondelete CASCADE to allow user deletion."""
    if not engine.url.drivername.startswith("sqlite"):
        return

    with engine.begin() as connection:
        table_exists = connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'audit_logs'"
            )
        ).first()

        if not table_exists:
            return

        # Check current foreign key
        fk_info = connection.execute(
            text("PRAGMA foreign_key_list(audit_logs)")
        ).fetchall()

        # For this table, check if the user_id constraint has no ON DELETE action
        for fk in fk_info:
            if fk[3] == "user_id" and fk[5] is None:  # fk[5] is the on_delete action
                # Need to recreate the table with proper CASCADE constraint
                connection.execute(text("PRAGMA foreign_keys = OFF"))
                try:
                    connection.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS audit_logs_new (
                                id INTEGER NOT NULL,
                                action VARCHAR NOT NULL,
                                entity_type VARCHAR NOT NULL,
                                entity_id INTEGER,
                                message VARCHAR NOT NULL,
                                details JSON,
                                created_at DATETIME NOT NULL,
                                user_id INTEGER,
                                PRIMARY KEY (id),
                                FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
                            )
                            """
                        )
                    )

                    connection.execute(
                        text(
                            """
                            INSERT INTO audit_logs_new
                            SELECT * FROM audit_logs
                            """
                        )
                    )

                    connection.execute(text("DROP TABLE audit_logs"))
                    connection.execute(
                        text("ALTER TABLE audit_logs_new RENAME TO audit_logs")
                    )
                finally:
                    connection.execute(text("PRAGMA foreign_keys = ON"))
                break


app = FastAPI()


def _database_host_hint() -> str:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return "DATABASE_URL not set"

    parsed = urlparse(database_url)
    return parsed.hostname or "Unable to parse host from DATABASE_URL"


def _initialize_database_with_retry() -> None:
    last_error: Exception | None = None

    for attempt in range(1, DB_INIT_MAX_RETRIES + 1):
        try:
            Base.metadata.create_all(bind=engine)
            _ensure_sqlite_tasks_columns()
            _repair_legacy_sqlite_sub_tasks_table()
            _ensure_sqlite_sub_tasks_timeline_columns()
            _ensure_sub_tasks_assigned_to_column()
            _ensure_audit_logs_cascade_delete()
            return
        except OperationalError as exc:
            last_error = exc
            if attempt < DB_INIT_MAX_RETRIES:
                print(
                    f"[startup-warning] Database initialization attempt {attempt}/{DB_INIT_MAX_RETRIES} failed; retrying in {DB_INIT_RETRY_DELAY_SECONDS}s"
                )
                time.sleep(DB_INIT_RETRY_DELAY_SECONDS)

    raise RuntimeError(
        "Database initialization failed after retries. "
        f"Check DATABASE_URL and DNS/network reachability. Parsed host: {_database_host_hint()}"
    ) from last_error


@app.on_event("startup")
def log_invalid_password_hash_count():
    _initialize_database_with_retry()

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

if allowed_origins == [""]:
    allowed_origins = [
        "http://localhost:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



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
app.include_router(departments.router)
app.include_router(activities.router)
app.include_router(sub_tasks.router)
app.include_router(audit_logs.router)
app.include_router(dashboard.router)
