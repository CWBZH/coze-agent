from pydantic import BaseModel


class ListResponse(BaseModel):
    items: list
    total: int
