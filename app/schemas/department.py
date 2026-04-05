from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DepartmentResponse(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True


class UserDepartmentAssignRequest(BaseModel):
    department_ids: list[int] = Field(default_factory=list)
