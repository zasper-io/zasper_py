from pydantic import BaseModel


class IdentityModel(BaseModel):
    username: str
    name: str
    display_name: str
