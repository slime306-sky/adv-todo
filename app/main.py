import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.database import Base, engine
from app.core.errors import (
	http_exception_handler,
	unhandled_exception_handler,
	validation_exception_handler,
)
from app.routers import activities, audit_logs, auth, sub_tasks, tasks, users

Base.metadata.create_all(bind=engine)

app = FastAPI()

# CORS — update ALLOWED_ORIGINS env var in Render to restrict to your frontend URL
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
