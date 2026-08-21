from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_current_user, get_db, require_role
from app.models.department import Department
from app.models.task import Task
from app.models.user import User
from app.schemas.department import DepartmentCreate, DepartmentResponse, UserDepartmentAssignRequest

router = APIRouter(tags=["departments"])


def _serialize_department(department: Department):
    return {"id": department.id, "name": department.name, "user_count": len(department.users)}


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
    departments = (
        db.query(Department, func.count(User.id).label("user_count"))
        .outerjoin(Department.users)
        .group_by(Department.id, Department.name)
        .order_by(Department.name.asc())
        .all()
    )
    return [
        {"id": department.id, "name": department.name, "user_count": user_count}
        for department, user_count in departments
    ]


@router.put("/departments/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: int,
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    department = db.query(Department).filter(Department.id == department_id).first()
    if not department:
        raise api_error(
            status_code=404,
            code="DEPARTMENT_NOT_FOUND",
            message="Department not found",
        )

    department_name = payload.name.strip()
    if not department_name:
        raise api_error(
            status_code=400,
            code="INVALID_DEPARTMENT_NAME",
            message="Department name cannot be empty",
        )

    existing = (
        db.query(Department)
        .filter(Department.id != department.id)
        .filter(Department.name.ilike(department_name))
        .first()
    )
    if existing:
        raise api_error(
            status_code=409,
            code="DEPARTMENT_ALREADY_EXISTS",
            message="Department already exists",
        )

    department.name = department_name

    log_audit_event(
        db=db,
        action="UPDATE",
        entity_type="department",
        entity_id=department.id,
        user_id=current_user.id,
        message="Department updated",
        details={"name": department.name},
    )
    db.commit()
    db.refresh(department)
    return _serialize_department(department)


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


@router.delete("/departments/{department_id}")
def delete_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    department = db.query(Department).filter(Department.id == department_id).first()
    if not department:
        raise api_error(
            status_code=404,
            code="DEPARTMENT_NOT_FOUND",
            message="Department not found",
        )

    db.query(Task).filter(Task.department_id == department.id).update(
        {Task.department_id: None},
        synchronize_session=False,
    )
    department.users = []

    log_audit_event(
        db=db,
        action="DELETE",
        entity_type="department",
        entity_id=department.id,
        user_id=current_user.id,
        message="Department deleted",
        details={"name": department.name},
    )

    db.delete(department)
    db.commit()

    return {"message": "Department deleted successfully"}


@router.get("/user_departments")
def get_my_departments(current_user: User = Depends(get_current_user)):
    return [{
        "id": department.id,
        "name": department.name,
    }
    for department in current_user.departments]

