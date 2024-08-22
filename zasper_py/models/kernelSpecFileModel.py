from pydantic import BaseModel


class KernelSpecFileModel(BaseModel):
    language: str
    argv: str
    display_name: str
    codemirror_mode: str
    env: str
    help_links: str
