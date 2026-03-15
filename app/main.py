import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.database import Base, SessionLocal, engine
from app.core.errors import (
	http_exception_handler,
	unhandled_exception_handler,
	validation_exception_handler,
)
from app.core.security import is_supported_password_hash
from app.models.user import User
from app.routers import activities, audit_logs, auth, sub_tasks, tasks, users

Base.metadata.create_all(bind=engine)

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
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

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
app.include_router(activities.router)
app.include_router(sub_tasks.router)
app.include_router(audit_logs.router)
