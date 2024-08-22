from pydantic import BaseModel


class KernelModel(BaseModel):
    id: str
    name: str
    last_activity: str
    connections: str
    execution_state: str
