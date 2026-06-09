from pydantic import BaseModel, Field


class FaqVariantRequest(BaseModel):
    question: str
    status: str = "active"
    operator: str = "admin"


class FaqVariantItem(BaseModel):
    variant_id: str
    faq_id: str
    question: str
    status: str
    operator: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class FaqItemCreateRequest(BaseModel):
    question: str
    answer: str
    category: str = "default"
    tags: list[str] = Field(default_factory=list)
    priority: int = 0
    operator: str = "admin"
    variants: list[str] = Field(default_factory=list)


class FaqItemUpdateRequest(BaseModel):
    question: str
    answer: str
    category: str = "default"
    tags: list[str] = Field(default_factory=list)
    priority: int = 0
    status: str = "active"
    operator: str = "admin"
    variants: list[str] | None = None


class FaqItem(BaseModel):
    faq_id: str
    question: str
    answer: str
    category: str
    tags: list[str]
    status: str
    priority: int
    hit_count: int
    operator: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    variant_count: int
    variants: list[FaqVariantItem] | None = None


class FaqItemListResponse(BaseModel):
    count: int
    items: list[FaqItem]


class FaqDeleteResponse(BaseModel):
    faq_id: str
    deleted: bool
    message: str


class FaqVariantDeleteResponse(BaseModel):
    faq_id: str
    variant_id: str
    deleted: bool
    message: str


class FaqRetrieveRequest(BaseModel):
    query: str
    top_k: int = 5
    category: str | None = None


class FaqRetrieveResult(BaseModel):
    faq_id: str
    question: str
    answer: str
    category: str
    tags: list[str]
    status: str
    priority: int
    hit_count: int
    updated_at: str
    matched_question: str
    matched_doc_type: str
    matched_doc_id: str
    sources: list[str]
    score: float
    bm25_score: float
    vector_score: float
    normalized_bm25_score: float
    normalized_vector_score: float


class FaqRetrieveResponse(BaseModel):
    query: str
    top_k: int
    category: str | None = None
    results: list[FaqRetrieveResult]
