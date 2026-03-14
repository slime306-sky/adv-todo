from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import create_access_token, get_db, hash_password, require_role, verify_password
from app.models.user import User
from app.schemas.auth import Token
from app.schemas.user import UserCreate

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
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password):
        raise api_error(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="Invalid credentials",
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
    return {"access_token": token, "token_type": "bearer"}
