from pydantic import BaseModel


class SecretModel(BaseModel):
    id: str
    project_id: str
    name: str
    value: str
