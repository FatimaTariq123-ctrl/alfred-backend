from pydantic import BaseModel


class SanctionEntity(BaseModel):
    ticker: str
    name: str
    regulatory_body: str
