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
