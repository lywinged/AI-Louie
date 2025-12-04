"""
Data models for RAG QA API (Task 3.2)
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Source citation for RAG response"""
    source: str = Field(..., description="Source document title")
    content: str = Field(..., description="Relevant text chunk")
    score: float = Field(..., description="Relevance score (0-1)")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")


class RAGRequest(BaseModel):
    """Request for RAG question answering"""
    question: str = Field(..., description="User's question", min_length=1)
    top_k: Optional[int] = Field(default=5, description="Number of results to return", ge=1, le=50)
    include_scores: bool = Field(default=True, description="Include relevance scores in response")
    include_timings: bool = Field(default=True, description="Return detailed timing breakdown")
    reranker: Optional[str] = Field(
        default=None,
        description="Reranker override: 'auto', 'primary', 'fallback', or explicit model path",
    )
    vector_limit: Optional[int] = Field(
        default=None,
        ge=5,
        le=50,
        description="Maximum candidate vectors to score during retrieval (5-50)",
    )
    content_char_limit: Optional[int] = Field(
        default=None,
        ge=150,
        le=1000,
        description="Maximum characters per chunk payload (150-1000)",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata for the request (e.g., search_scope for multi-collection search)",
    )


class RAGResponse(BaseModel):
    """Response from RAG QA"""
    answer: str = Field(..., description="Generated answer")
    citations: List[Citation] = Field(default_factory=list, description="Source citations")
    retrieval_time_ms: float = Field(..., description="Retrieval latency in milliseconds")
    confidence: float = Field(..., description="Answer confidence score (0-1)")
    num_chunks_retrieved: int = Field(..., description="Number of chunks retrieved")
    llm_time_ms: float = Field(default=0.0, description="LLM generation latency in milliseconds")
    total_time_ms: float = Field(default=0.0, description="End-to-end latency in milliseconds")
    query_id: Optional[str] = Field(
        default=None,
        description="Unique query ID for feedback correlation",
    )
    timings: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed timing breakdown for embedding, vector search, rerank, etc.",
    )
    models: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Model metadata (embedding, reranker, llm)",
    )
    token_usage: Optional[Dict[str, int]] = Field(
        default=None,
        description="LLM token usage {'prompt': int, 'completion': int, 'total': int}",
    )
    token_cost_usd: Optional[float] = Field(
        default=None,
        description="Estimated LLM cost in USD for generating the answer",
    )
    llm_used: bool = Field(default=True, description="Whether an LLM was used to generate the answer")
    cache_hit: Optional[bool] = Field(
        default=None,
        description="Whether answer was retrieved from cache (True=cached, False=freshly generated, None=cache not used)",
    )
    reranker_mode: Optional[str] = Field(
        default=None,
        description="Reranker strategy applied for this request",
    )
    vector_limit_used: Optional[int] = Field(
        default=None,
        description="Candidate vector limit applied during retrieval",
    )
    content_char_limit_used: Optional[int] = Field(
        default=None,
        description="Character truncation limit applied to chunks",
    )
    selected_strategy: Optional[str] = Field(
        default=None,
        description="RAG strategy selected by Smart RAG (e.g., 'Hybrid RAG', 'Iterative Self-RAG')",
    )
    strategy_reason: Optional[str] = Field(
        default=None,
        description="Reason why this strategy was selected (query type and description)",
    )
    iteration_details: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Per-iteration breakdown for Iterative Self-RAG (token usage, confidence, etc.)",
    )
    token_breakdown: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed breakdown of token usage across all pipeline stages",
    )
    governance_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="AI Governance context including risk tier, criteria, and checkpoints",
    )


class DocumentUpload(BaseModel):
    """Request to upload a document for RAG"""
    title: str = Field(..., description="Document title")
    content: str = Field(..., description="Document content", min_length=10)
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Document metadata")
    source: Optional[str] = Field(default=None, description="Document source")


class DocumentResponse(BaseModel):
    """Response after document upload"""
    document_id: int = Field(..., description="ID of uploaded document")
    title: str = Field(..., description="Document title")
    num_chunks: int = Field(..., description="Number of chunks created")
    embedding_time_ms: float = Field(..., description="Embedding time in milliseconds")


class UserFeedback(BaseModel):
    """User feedback on RAG response quality"""
    query_id: str = Field(..., description="Query ID from RAGResponse", min_length=1)
    rating: float = Field(
        ...,
        description="User rating: 1.0 (satisfied/correct), 0.0 (unsatisfied/incorrect), or 0.5 (neutral)",
        ge=0.0,
        le=1.0,
    )
    comment: Optional[str] = Field(
        default=None,
        description="Optional user comment explaining the rating",
        max_length=500,
    )


class FeedbackResponse(BaseModel):
    """Response after submitting feedback"""
    query_id: str = Field(..., description="Query ID that received feedback")
    rating: float = Field(..., description="Feedback rating applied")
    strategy_updated: Optional[str] = Field(
        default=None,
        description="Strategy that was re-evaluated based on feedback",
    )
    bandit_updated: bool = Field(
        default=False,
        description="Whether bandit weights were updated",
    )
    message: str = Field(..., description="Confirmation message")
