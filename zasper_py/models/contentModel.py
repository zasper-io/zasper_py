from pydantic import BaseModel


class ContentModel(BaseModel):
    name: str
    path: str
    type: str
    writable: str
    created: str
    last_modified: str
    size: str
    mimetype: str
    content: str
    format: str
    hash: str
    hash_algorithm: str
