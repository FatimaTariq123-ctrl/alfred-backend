from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_key: str | None = None
    stream: bool = False


class ChatResponse(BaseModel):
    response: str
    session_key: str | None = None
