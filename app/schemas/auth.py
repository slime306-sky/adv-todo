from pydantic import BaseModel

from app.schemas.user import UserReference


class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str
    user: UserReference
