from secrets import choice
from string import ascii_letters, digits

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_db, hash_password, is_supported_password_hash, require_role
from app.models.user import User
from app.schemas.user import PasswordRemediationResponse, PasswordRemediationUser, UserResponse, UserUpdate

router = APIRouter(tags=["users"])


def _generate_temporary_password(length: int = 16) -> str:
    alphabet = ascii_letters + digits
    return "".join(choice(alphabet) for _ in range(length))


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

    if "password" in update_data:
        raise api_error(
            status_code=400,
            code="PASSWORD_UPDATE_NOT_ALLOWED",
            message="Use dedicated password change flow",
        )

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


@router.post("/users/remediate-passwords", response_model=PasswordRemediationResponse)
def remediate_invalid_passwords(
    dry_run: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    users = db.query(User).order_by(User.id.asc()).all()

    affected_users: list[PasswordRemediationUser] = []

    for user in users:
        if len(affected_users) >= limit:
            break

        if is_supported_password_hash(user.password):
            continue

        temporary_password = _generate_temporary_password()
        affected_users.append(
            PasswordRemediationUser(
                user_id=user.id,
                username=user.username,
                email=user.email,
                temporary_password=temporary_password,
            )
        )

        if not dry_run:
            user.password = hash_password(temporary_password)

    if not dry_run and affected_users:
        log_audit_event(
            db=db,
            action="PASSWORD_REMEDIATION",
            entity_type="user",
            user_id=current_user.id,
            message="Admin rotated invalid user passwords",
            details={
                "rotated_count": len(affected_users),
                "rotated_user_ids": [u.user_id for u in affected_users],
            },
        )
        db.commit()

    return {
        "processed_users": len(affected_users),
        "affected_users": affected_users,
    }


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
