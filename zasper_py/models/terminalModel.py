from pydantic import BaseModel


class TerminalModel(BaseModel):
    name: str
    last_activity: str
