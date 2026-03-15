import uuid

from fastapi import HTTPException
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def api_error(
    status_code: int,
    code: str,
    message: str,
    dev_message: str | None = None,
    details: list | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "message": message,
            "code": code,
            "dev_message": dev_message or message,
            "details": details,
        },
    )


def _default_error_code(status_code: int) -> str:
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        500: "INTERNAL_SERVER_ERROR",
    }
    return mapping.get(status_code, f"HTTP_{status_code}")


def _build_error_payload(
    request: Request,
    status_code: int,
    message: str,
    code: str | None = None,
    dev_message: str | None = None,
    details: list | None = None,
):
    request_id = getattr(request.state, "request_id", None) or request.headers.get("x-request-id") or str(uuid.uuid4())
    payload = {
        "message": message,
        "code": code or _default_error_code(status_code),
        "dev_message": dev_message or message,
        "request_id": request_id,
        "path": request.url.path,
    }
    if details is not None:
        payload["details"] = details
    return payload


def _parse_http_detail(detail, status_code: int):
    if isinstance(detail, dict):
        return (
            detail.get("message") or detail.get("detail") or "Request failed",
            detail.get("code") or _default_error_code(status_code),
            detail.get("dev_message")
            or detail.get("developer_message")
            or detail.get("detail")
            or "Request failed",
            detail.get("details"),
        )

    message = str(detail) if detail else "Request failed"
    return message, _default_error_code(status_code), message, None


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    message, code, dev_message, details = _parse_http_detail(exc.detail, exc.status_code)
    payload = _build_error_payload(
        request=request,
        status_code=exc.status_code,
        message=message,
        code=code,
        dev_message=dev_message,
        details=details,
    )
    return JSONResponse(status_code=exc.status_code, content=payload)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    payload = _build_error_payload(
        request=request,
        status_code=422,
        message="Validation failed",
        code="VALIDATION_ERROR",
        dev_message="One or more request fields are invalid",
        details=exc.errors(),
    )
    return JSONResponse(status_code=422, content=payload)


async def unhandled_exception_handler(request: Request, exc: Exception):
    payload = _build_error_payload(
        request=request,
        status_code=500,
        message="Internal server error",
        code="INTERNAL_SERVER_ERROR",
        dev_message=str(exc),
    )
    return JSONResponse(status_code=500, content=payload)
