from pydantic import BaseModel


class VetoRequest(BaseModel):
    ledger_id: str
    veto_type: str
    veto_reason: str
