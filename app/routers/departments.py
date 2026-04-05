from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db, require_role
from app.models.department import Department
from app.models.user import User
from app.schemas.department import DepartmentCreate, DepartmentResponse, UserDepartmentAssignRequest

router = APIRouter(tags=["departments"])


def _serialize_department(department: Department):
    return {"id": department.id, "name": department.name}


@router.post("/departments", response_model=DepartmentResponse)
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    department_name = payload.name.strip()
    if not department_name:
        raise api_error(
            status_code=400,
            code="INVALID_DEPARTMENT_NAME",
            message="Department name cannot be empty",
        )

    existing = db.query(Department).filter(Department.name.ilike(department_name)).first()
    if existing:
        raise api_error(
            status_code=409,
            code="DEPARTMENT_ALREADY_EXISTS",
            message="Department already exists",
        )

    department = Department(name=department_name)
    db.add(department)
    db.flush()

    log_audit_event(
        db=db,
        action="CREATE",
        entity_type="department",
        entity_id=department.id,
        user_id=current_user.id,
        message="Department created",
        details={"name": department.name},
    )
    db.commit()
    db.refresh(department)
    return _serialize_department(department)


@router.get("/departments", response_model=list[DepartmentResponse])
def get_departments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    departments = db.query(Department).order_by(Department.name.asc()).all()
    return [_serialize_department(department) for department in departments]


@router.put("/users/{user_id}/departments")
def assign_user_departments(
    user_id: int,
    payload: UserDepartmentAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise api_error(status_code=404, code="USER_NOT_FOUND", message="User not found")

    department_ids = list(dict.fromkeys(payload.department_ids))
    if not department_ids:
        user.departments = []
        log_audit_event(
            db=db,
            action="UPDATE",
            entity_type="user",
            entity_id=user.id,
            user_id=current_user.id,
            message="User departments cleared",
            details={"department_ids": []},
        )
        db.commit()
        return {"message": "User departments updated", "department_ids": []}

    departments = db.query(Department).filter(Department.id.in_(department_ids)).all()
    found_ids = {department.id for department in departments}
    missing_ids = [department_id for department_id in department_ids if department_id not in found_ids]
    if missing_ids:
        raise api_error(
            status_code=404,
            code="DEPARTMENT_NOT_FOUND",
            message="One or more departments not found",
            details=missing_ids,
        )

    user.departments = departments
    log_audit_event(
        db=db,
        action="UPDATE",
        entity_type="user",
        entity_id=user.id,
        user_id=current_user.id,
        message="User departments updated",
        details={"department_ids": department_ids},
    )
    db.commit()

    return {"message": "User departments updated", "department_ids": department_ids}
