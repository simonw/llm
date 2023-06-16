from pydantic import BaseModel
from typing import Optional


class Template(BaseModel):
    name: str
    prompt: Optional[str]
    system: Optional[str]
    model: Optional[str]

    class Config:
        extra = "forbid"
