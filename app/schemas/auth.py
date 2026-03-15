from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str
