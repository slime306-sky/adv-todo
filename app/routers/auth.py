from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import (
    create_access_token,
    get_current_user,
    get_db,
    hash_password,
    is_supported_password_hash,
    require_role,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import Token
from app.schemas.user import PasswordChangeRequest, UserCreate, UserLogin

router = APIRouter(tags=["auth"])


@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise api_error(
            status_code=400,
            code="USERNAME_ALREADY_EXISTS",
            message="Username already exists",
        )

    hashed = hash_password(user.password)
    new_user = User(
        username=user.username,
        email=user.email,
        password=hashed,
        role=user.role,
    )
    db.add(new_user)
    log_audit_event(
        db=db,
        action="CREATE",
        entity_type="user",
        user_id=current_user.id,
        message="User account created",
        details={"username": user.username, "role": user.role},
    )
    db.commit()
    db.refresh(new_user)
    return {"message": "User created"}


@router.post("/login", response_model=Token)
def login(
    payload: UserLogin, db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user:
        raise api_error(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="Invalid credentials",
        )

    if is_supported_password_hash(user.password):
        if not verify_password(payload.password, user.password):
            raise api_error(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="Invalid credentials",
            )
    else:
        # Legacy fallback: allow one successful plaintext login, then upgrade to hash.
        if not user.password or payload.password != user.password:
            raise api_error(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="Invalid credentials",
            )

        user.password = hash_password(payload.password)
        log_audit_event(
            db=db,
            action="PASSWORD_MIGRATION",
            entity_type="user",
            entity_id=user.id,
            user_id=user.id,
            message="Legacy plaintext password migrated to hash on login",
            details={"username": user.username},
        )

    log_audit_event(
        db=db,
        action="LOGIN",
        entity_type="auth",
        entity_id=user.id,
        user_id=user.id,
        message="User logged in",
        details={"username": user.username},
    )
    db.commit()

    token = create_access_token({"sub": user.username, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
        "user": {"id": user.id, "name": user.username},
    }


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.new_password:
        raise api_error(
            status_code=400,
            code="INVALID_PASSWORD",
            message="New password is required",
        )

    if not current_user.password or not verify_password(
        payload.current_password or "", current_user.password
    ):
        raise api_error(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="Current password is invalid",
        )

    current_user.password = hash_password(payload.new_password)
    log_audit_event(
        db=db,
        action="PASSWORD_CHANGE",
        entity_type="user",
        entity_id=current_user.id,
        user_id=current_user.id,
        message="User changed password",
        details={"username": current_user.username},
    )
    db.commit()

    return {"message": "Password changed successfully"}
