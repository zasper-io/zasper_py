from pydantic import BaseModel


class SessionModel(BaseModel):
    id: str
    path: str
    name: str
    type: str
    kernel: str
