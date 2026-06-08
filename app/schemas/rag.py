from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    chunk_id: str | None = None
    chunk_hash: str | None = None
    document_id: str | None = None
    document_hash: str | None = None
    chunk_index: int | None = None
    source: str | None = None
    created_at: str | None = None
    operator: str | None = None
    text_length: int | None = None


class ChunkItem(BaseModel):
    id: str
    chunk_id: str
    chunk_hash: str
    document_id: str
    chunk_index: int
    text: str
    text_length: int
    source: str
    status: str
    operator: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    metadata: ChunkMetadata


class DocumentItem(BaseModel):
    document_id: str
    document_hash: str
    filename: str
    source: str
    content_type: str | None = None
    size_bytes: int
    status: str
    active_chunk_count: int
    total_chunk_count: int
    added_chunk_count: int
    reassigned_chunk_count: int
    operator: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    chunks: list[ChunkItem]


class DocumentListResponse(BaseModel):
    count: int
    documents: list[DocumentItem]


class UploadDocumentResponse(BaseModel):
    document_id: str
    document_hash: str
    filename: str
    content_type: str | None = None
    status: str
    is_duplicate: bool
    chunk_count: int
    active_chunk_count: int
    added_chunk_count: int
    reassigned_chunk_count: int
    message: str


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 5


class RetrieveResultItem(BaseModel):
    id: str
    text: str
    metadata: ChunkMetadata
    score: float


class RetrieveResponse(BaseModel):
    query: str
    top_k: int
    results: list[RetrieveResultItem]


class DeleteDocumentResponse(BaseModel):
    document_id: str
    deleted: bool
    deleted_chunk_count: int
    message: str


class DeleteDocumentChunkResponse(BaseModel):
    document_id: str
    chunk_id: str
    deleted: bool
    document_status: str
    remaining_chunks: int
    message: str
