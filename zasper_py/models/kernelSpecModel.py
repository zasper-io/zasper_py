import json

from pydantic import BaseModel


class KernelSpecModel(BaseModel):
    argv: list
    name: str = ""
    mimetype: str = ""
    display_name: str
    language: str = ""
    env: str = ""
    resource_dir: str = ""
    interrupt_mode: str = ""
    # enum(["message", "signal"], default_value="signal")
    metadata: dict
