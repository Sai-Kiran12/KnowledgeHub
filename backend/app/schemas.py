from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: str = Field(pattern='^(user|assistant)$')
    content: str = Field(min_length=1)


class RetrievalFilters(BaseModel):
    owner_id: str | None = None
    tenant_id: str | None = None
    file_type: str | None = None
    tags: list[str] | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=2)
    top_k: int | None = None
    history: list[ChatTurn] = []
    filters: RetrievalFilters | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]


class AskWithFileResponse(BaseModel):
    answer: str
    sources: list[dict]


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]


class UploadResponse(BaseModel):
    filename: str
    chunks_indexed: int
    doc_id: str | None = None


class HealthResponse(BaseModel):
    status: str
