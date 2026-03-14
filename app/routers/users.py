from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_db, require_role
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserResponse])
def get_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    users = db.query(User).all()
    return users


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise api_error(status_code=404, code="USER_NOT_FOUND", message="User not found")

    update_data = user_update.dict(exclude_unset=True)

    if user.id == current_user.id and "role" in update_data:
        raise api_error(
            status_code=400,
            code="SELF_ROLE_CHANGE_NOT_ALLOWED",
            message="Admin cannot change own role",
        )

    if "role" in update_data and update_data["role"] not in ["admin", "user"]:
        raise api_error(status_code=400, code="INVALID_ROLE", message="Invalid role")

    for key, value in update_data.items():
        setattr(user, key, value)

    log_audit_event(
        db=db,
        action="UPDATE",
        entity_type="user",
        entity_id=user.id,
        user_id=current_user.id,
        message="User updated",
        details={"updated_fields": list(update_data.keys())},
    )
    db.commit()
    db.refresh(user)

    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise api_error(status_code=404, code="USER_NOT_FOUND", message="User not found")

    if user.id == current_user.id:
        raise api_error(
            status_code=400,
            code="SELF_DELETE_NOT_ALLOWED",
            message="Admin cannot delete themselves",
        )

    log_audit_event(
        db=db,
        action="DELETE",
        entity_type="user",
        entity_id=user.id,
        user_id=current_user.id,
        message="User deleted",
        details={"username": user.username},
    )
    db.delete(user)
    db.commit()

    return {"message": "User deleted successfully"}
