from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DepartmentResponse(BaseModel):
    id: int
    name: str
    user_count: int = Field(ge=0, default=0)

    class Config:
        from_attributes = True


class UserDepartmentAssignRequest(BaseModel):
    department_ids: list[int] = Field(default_factory=list)
