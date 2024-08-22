from typing import List, Optional, Union

from pydantic import BaseModel


class ProjectModel(BaseModel):
    id: str
    name: str
    description: str
    total: int
    running: int
    completed: int
