from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.errors import api_error
from app.core.security import get_db, require_role
from app.models.category import Category
from app.models.task import Task
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryResponse

router = APIRouter(tags=["categories"])


def _serialize_category(category: Category):
    return {"id": category.id, "name": category.name}


@router.post("/categories", response_model=CategoryResponse)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    category_name = payload.name.strip()
    if not category_name:
        raise api_error(
            status_code=400,
            code="INVALID_CATEGORY_NAME",
            message="Category name cannot be empty",
        )

    existing = db.query(Category).filter(Category.name.ilike(category_name)).first()
    if existing:
        raise api_error(
            status_code=409,
            code="CATEGORY_ALREADY_EXISTS",
            message="Category already exists",
        )

    category = Category(name=category_name)
    db.add(category)
    db.flush()

    log_audit_event(
        db=db,
        action="CREATE",
        entity_type="category",
        entity_id=category.id,
        user_id=current_user.id,
        message="Category created",
        details={"name": category.name},
    )
    db.commit()
    db.refresh(category)
    return _serialize_category(category)


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise api_error(
            status_code=404,
            code="CATEGORY_NOT_FOUND",
            message="Category not found",
        )

    db.query(Task).filter(Task.category_id == category.id).update(
        {Task.category_id: None},
        synchronize_session=False,
    )
    db.delete(category)

    log_audit_event(
        db=db,
        action="DELETE",
        entity_type="category",
        entity_id=category.id,
        user_id=current_user.id,
        message="Category deleted",
        details={"name": category.name},
    )
    db.commit()
    return {"message": "Category deleted successfully"}