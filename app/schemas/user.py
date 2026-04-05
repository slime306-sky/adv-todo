from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"


class UserReference(BaseModel):
    id: int
    name: str


class DepartmentReference(BaseModel):
    id: int
    name: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    departments: list[DepartmentReference] = Field(default_factory=list)

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    role: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str | None = None
    new_password: str


class PasswordRemediationUser(BaseModel):
    user_id: int
    username: str
    email: str | None
    temporary_password: str


class PasswordRemediationResponse(BaseModel):
    processed_users: int
    affected_users: list[PasswordRemediationUser]
