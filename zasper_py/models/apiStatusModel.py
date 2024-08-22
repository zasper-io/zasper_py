from pydantic import BaseModel


class ApiStatusModel(BaseModel):
    started: str
    last_activity: str
    connections: str
    kernels: str
