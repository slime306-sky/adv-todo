<<<<<<< HEAD
from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"


class UserResponse(BaseModel):
    username: str
    email: str
    role: str

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
=======
from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"


class UserResponse(BaseModel):
    username: str
    email: str
    role: str

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    role: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str
>>>>>>> 9c962f1627ff7435b1f0ba63448f07959fba9ec1
