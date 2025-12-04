# Comprehensive RAG Strategy for AI-Louie Book QA System

## Executive Summary

This document synthesizes all discussed improvements for the RAG (Retrieval-Augmented Generation) system, prioritized by impact and implementation complexity. The strategy focuses on improving accuracy for complex book queries while optimizing token usage and enabling continuous learning.

---

## 1. Current System Status (✅ Implemented)

### 1.1 Model Transparency
- **Issue**: Model names showing service URLs instead of actual ONNX model paths
- **Fix**: Modified `rag_pipeline.py` to return actual model paths from settings
- **Impact**: Users now see "minilm-embed-int8" instead of "http://inference:8001"

### 1.2 Retrieval Recall Improvements
- **Issue**: Only 3-8 documents retrieved for complex queries
- **Fixes**:
  - Increased `vector_limit` from 8 → 50 (lines 342 in rag_pipeline.py)
  - Lowered `RERANK_SCORE_THRESHOLD` from -1.0 → -20.0 (.env)
  - Increased API `top_k` limit from 20 → 50 (rag_schemas.py)
- **Impact**: Better recall for complex queries, more candidate documents

### 1.3 Quality Control
- **Implementation**: Limit LLM analysis to top 30 documents (line 682-683)
- **Rationale**: Balance between recall and precision, prevent irrelevant documents
- **Impact**: Higher relevance ratio in final answers

### 1.4 Reasoning Transparency
- **Implementation**: Enhanced prompt to require step-by-step reasoning (lines 545-563)
- **Format**:
  ```
  **Reasoning:**
  [Analysis process, source evaluation, inference steps]

  **Answer:**
  [Final answer with citations]
  ```
- **Impact**: Users understand how LLM arrived at conclusions

---

## 2. Priority 1: Hybrid Search (Keyword + Semantic)

### 2.1 Why BM25 Hybrid Search?

**Problem**: Pure vector search misses exact keyword matches
- Example: Query "Sir Robert cheating uncle" may miss documents with exact phrase
- Vector embeddings may not capture rare proper nouns or specific phrases

**Solution**: Combine BM25 (keyword) + Dense Vector (semantic) retrieval

### 2.2 Architecture

```
Query → [BM25 Retrieval] → Top 25 keyword matches (score_bm25)
     ↓
     → [Vector Retrieval] → Top 50 semantic matches (score_vector)
     ↓
     → [Score Fusion] → Weighted combination: 0.3*BM25 + 0.7*Vector
     ↓
     → [Reranker] → Top 30 for LLM
```

### 2.3 Implementation Plan

**File**: `backend/backend/services/hybrid_retriever.py` (new)

```python
from typing import List, Dict, Tuple
from rank_bm25 import BM25Okapi
import numpy as np

class HybridRetriever:
    """Combines BM25 keyword search with dense vector retrieval"""

    def __init__(self, qdrant_client, collection_name: str):
        self.qdrant = qdrant_client
        self.collection = collection_name
        self.bm25_index = None
        self.doc_corpus = []

    async def initialize_bm25(self):
        """Build BM25 index from Qdrant collection"""
        # Fetch all document texts from Qdrant
        # Tokenize and build BM25Okapi index
        pass

    async def hybrid_search(
        self,
        query: str,
        query_embedding: List[float],
        top_k: int = 50,
        alpha: float = 0.7  # Weight for vector vs BM25 (0.7 = 70% vector, 30% BM25)
    ) -> List[Dict]:
        """
        Hybrid retrieval combining BM25 and vector search

        Args:
            query: Raw text query
            query_embedding: Dense vector embedding
            top_k: Final number of results
            alpha: Vector weight (1-alpha = BM25 weight)

        Returns:
            List of chunks with fused scores
        """
        # 1. BM25 retrieval
        bm25_scores = self.bm25_index.get_scores(query.split())
        bm25_top_k = np.argsort(bm25_scores)[-50:][::-1]  # Top 50 BM25

        # 2. Vector retrieval
        vector_results = await self.qdrant.search(
            collection_name=self.collection,
            query_vector=query_embedding,
            limit=50
        )

        # 3. Score fusion (Reciprocal Rank Fusion or Weighted Sum)
        fused_results = self._fuse_scores(bm25_top_k, vector_results, alpha)

        return fused_results[:top_k]
```

**Integration**: Modify `rag_pipeline.py` line ~320-350 to use `HybridRetriever`

**Configuration** (.env):
```bash
ENABLE_HYBRID_SEARCH=true
HYBRID_ALPHA=0.7  # 70% vector, 30% BM25
BM25_TOP_K=25
```

**Estimated Impact**:
- +15-20% accuracy on exact keyword queries
- Minimal latency increase (~50ms for BM25 scoring)

---

## 3. Priority 2: Query Strategy Caching (90% Token Savings)

### 3.1 Problem: Expensive First Searches

**Observation**: Similar queries waste tokens repeating the same retrieval process
- "Who wrote Pride and Prejudice?" → Full RAG pipeline (1500 tokens)
- "Who is the author of Pride and Prejudice?" → Same pipeline again (1500 tokens)

**Waste**: ~3000 tokens for semantically identical queries

### 3.2 Solution: Cache Successful Retrieval Strategies

```
Query → [Pattern Matcher] → Check if similar query exists in cache
       ↓ (No match)          ↓ (Match found)
       ↓                      ↓
    [Full RAG]          [Cached Strategy]
       ↓                      ↓
    [Extract Strategy]   [Apply: vector_limit=20, filters=author]
       ↓                      ↓
    [Cache Pattern]      [Retrieve with strategy]
       ↓                      ↓
    [Answer]             [Answer] (90% fewer tokens)
```

### 3.3 Implementation Plan

**File**: `backend/backend/services/query_cache.py` (new)

```python
from typing import Dict, Optional, List
import hashlib
from sentence_transformers import SentenceTransformer
import numpy as np

class QueryStrategyCache:
    """Cache successful retrieval strategies for similar queries"""

    def __init__(self, similarity_threshold: float = 0.85):
        self.cache: Dict[str, Dict] = {}
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self.threshold = similarity_threshold

    def _get_query_embedding(self, query: str) -> np.ndarray:
        """Embed query for similarity matching"""
        return self.embedder.encode(query, normalize_embeddings=True)

    async def find_similar_query(self, query: str) -> Optional[Dict]:
        """
        Find cached strategy for similar query

        Returns:
            {
                'strategy': {
                    'vector_limit': 20,
                    'filters': {'metadata.type': 'chapter'},
                    'reranker_mode': 'primary'
                },
                'confidence': 0.92
            }
        """
        query_emb = self._get_query_embedding(query)

        best_match = None
        best_score = 0.0

        for cached_query, cache_data in self.cache.items():
            cached_emb = cache_data['embedding']
            similarity = np.dot(query_emb, cached_emb)

            if similarity > best_score and similarity > self.threshold:
                best_score = similarity
                best_match = cache_data

        if best_match:
            return {
                'strategy': best_match['strategy'],
                'confidence': best_score
            }
        return None

    async def cache_strategy(
        self,
        query: str,
        strategy: Dict,
        success_score: float
    ):
        """
        Cache successful retrieval strategy

        Args:
            query: Original query text
            strategy: Retrieval parameters used
            success_score: Confidence/relevance score (0-1)
        """
        query_emb = self._get_query_embedding(query)
        query_hash = hashlib.md5(query.encode()).hexdigest()

        self.cache[query_hash] = {
            'query': query,
            'embedding': query_emb,
            'strategy': strategy,
            'success_score': success_score,
            'timestamp': datetime.now(),
            'usage_count': 0
        }
```

**Integration in `rag_pipeline.py`**:

```python
# Line ~280 (before retrieval)
strategy_cache = QueryStrategyCache()

# Check cache first
cached = await strategy_cache.find_similar_query(question)
if cached and cached['confidence'] > 0.85:
    # Use cached strategy
    vector_limit = cached['strategy']['vector_limit']
    reranker_mode = cached['strategy']['reranker_mode']
    # Skip to retrieval with optimized params
else:
    # Full RAG pipeline
    # After successful retrieval:
    await strategy_cache.cache_strategy(
        question,
        strategy={
            'vector_limit': vector_limit_used,
            'reranker_mode': reranker_mode,
            'filters': applied_filters
        },
        success_score=confidence
    )
```

**Estimated Impact**:
- 90% token reduction for repeated similar queries
- ~200ms faster response time (skip embedding + initial retrieval)

---

## 4. Priority 3: Self-RAG with Confidence Thresholds

### 4.1 Problem: Single-Pass Retrieval May Miss Context

**Current Flow**:
```
Query → Retrieve → Rerank → LLM → Answer (even if low confidence)
```

**Issue**: LLM generates answer even when retrieved context is insufficient

### 4.2 Solution: Iterative Retrieval with Self-Reflection

```
Query → [Retrieve] → [LLM: Check Sufficiency]
                          ↓
                    [Confidence < 0.7?]
                          ↓ Yes
                    [Generate Follow-up Query]
                          ↓
                    [Retrieve More Context]
                          ↓
                    [LLM: Re-evaluate]
                          ↓
                    [Confidence > 0.7] → Answer
```

### 4.3 Implementation Plan

**File**: `backend/backend/services/self_rag.py` (new)

```python
from typing import List, Dict, Tuple
import asyncio

class SelfRAG:
    """Iterative retrieval with self-reflection and confidence thresholds"""

    def __init__(
        self,
        rag_pipeline,
        confidence_threshold: float = 0.7,
        max_iterations: int = 3
    ):
        self.pipeline = rag_pipeline
        self.threshold = confidence_threshold
        self.max_iterations = max_iterations

    async def ask_with_reflection(
        self,
        question: str,
        context: List[Dict] = None
    ) -> Tuple[str, float, List[Dict]]:
        """
        Iteratively retrieve and reflect until confidence threshold met

        Returns:
            (answer, confidence, all_retrieved_chunks)
        """
        iteration = 0
        all_chunks = context or []

        while iteration < self.max_iterations:
            # 1. Generate answer with current context
            result = await self.pipeline.generate_answer(question, all_chunks)
            answer = result['answer']
            confidence = result['confidence']

            # 2. Check if confidence meets threshold
            if confidence >= self.threshold:
                return answer, confidence, all_chunks

            # 3. Self-reflection: Why is confidence low?
            reflection = await self._reflect_on_insufficiency(
                question, all_chunks, answer
            )

            # 4. Generate follow-up query
            follow_up = reflection['follow_up_query']

            # 5. Retrieve additional context
            new_chunks = await self.pipeline.retrieve(follow_up, top_k=10)

            # 6. Merge new chunks (avoid duplicates)
            all_chunks = self._merge_chunks(all_chunks, new_chunks)

            iteration += 1

        # Max iterations reached, return best attempt
        return answer, confidence, all_chunks

    async def _reflect_on_insufficiency(
        self,
        question: str,
        context: List[Dict],
        answer: str
    ) -> Dict:
        """
        Use LLM to analyze why confidence is low and suggest follow-up query

        Prompt:
        "You attempted to answer the question but confidence is low.
        Analyze what information is missing and suggest a follow-up query.

        Question: {question}
        Current Answer: {answer}
        Context Analyzed: {len(context)} chunks

        What additional information would help answer this question more confidently?"
        """
        reflection_prompt = f"""You are analyzing why a RAG system has low confidence.

Question: {question}
Current Answer: {answer}
Context Chunks: {len(context)}

What information is missing? Suggest a follow-up query to retrieve additional context.

Respond in JSON:
{{
    "missing_info": "What specific information is needed",
    "follow_up_query": "A retrieval query to find missing info"
}}
"""

        reflection = await self.pipeline.llm_client.complete(reflection_prompt)
        return json.loads(reflection)
```

**Integration in `rag_routes.py`**:

```python
# Add new endpoint for self-RAG
@router.post("/api/rag/ask-iterative", response_model=RAGResponse)
async def ask_question_iterative(request: RAGRequest):
    """RAG endpoint with self-reflection and iterative retrieval"""
    self_rag = SelfRAG(
        rag_pipeline=app.state.rag_pipeline,
        confidence_threshold=0.75,
        max_iterations=3
    )

    answer, confidence, all_chunks = await self_rag.ask_with_reflection(
        question=request.question
    )

    return RAGResponse(
        answer=answer,
        confidence=confidence,
        citations=all_chunks[:10],
        num_chunks_retrieved=len(all_chunks)
    )
```

**Configuration** (.env):
```bash
ENABLE_SELF_RAG=true
SELF_RAG_CONFIDENCE_THRESHOLD=0.75
SELF_RAG_MAX_ITERATIONS=3
```

**Estimated Impact**:
- +25-30% accuracy on complex queries requiring multi-hop reasoning
- ~2-3x latency for queries requiring iterations (acceptable trade-off)

---

## 5. Priority 4: Incremental Context (Token Optimization)

### 5.1 Problem: Sending Duplicate Context in Iterations

**Current Issue in Self-RAG**:
```
Iteration 1: Send 20 chunks (5000 tokens)
Iteration 2: Send 20 old + 10 new = 30 chunks (7500 tokens)
Iteration 3: Send 30 old + 10 new = 40 chunks (10000 tokens)

Total: 22,500 tokens (mostly duplicates!)
```

### 5.2 Solution: Send Only New Documents

```
Iteration 1: Send 20 chunks (5000 tokens)
            ↓
        [LLM maintains state]
            ↓
Iteration 2: Send "You previously saw chunks [1-20]. Here are 10 new chunks [21-30]"
            (1500 tokens for new context only)
            ↓
Iteration 3: "You now have chunks [1-30]. Here are 10 more [31-40]"
            (1500 tokens)

Total: 8000 tokens (64% reduction!)
```

### 5.3 Implementation Plan

**Modify `self_rag.py`**:

```python
class SelfRAG:
    async def ask_with_reflection(self, question: str) -> Tuple[str, float, List[Dict]]:
        iteration = 0
        all_chunks = []
        conversation_history = []

        while iteration < self.max_iterations:
            if iteration == 0:
                # First iteration: full context
                prompt = self._build_full_prompt(question, all_chunks)
            else:
                # Subsequent iterations: incremental context
                prompt = self._build_incremental_prompt(
                    question,
                    new_chunks=all_chunks[len(all_chunks)-10:],  # Only last 10 new
                    chunk_range=f"[1-{len(all_chunks)-10}]",
                    conversation_history=conversation_history
                )

            result = await self.pipeline.llm_client.complete(prompt)
            conversation_history.append({
                'iteration': iteration,
                'prompt': prompt,
                'response': result
            })

            # ... rest of reflection logic

    def _build_incremental_prompt(
        self,
        question: str,
        new_chunks: List[Dict],
        chunk_range: str,
        conversation_history: List[Dict]
    ) -> str:
        """Build prompt that references previous context without repeating it"""
        return f"""You are continuing to answer a question with new retrieved context.

Question: {question}

Previously Retrieved Context: Chunks {chunk_range}
(You analyzed these in previous iterations - they are still available)

NEW Context (just retrieved):
{self._format_chunks(new_chunks)}

Based on ALL context (previous + new), provide your updated answer.

Previous Analysis:
{conversation_history[-1]['response']}

Updated Answer:"""
```

**Estimated Impact**:
- 60-70% token reduction in iterative retrieval scenarios
- Maintains full context awareness via conversation history

---

## 6. Priority 5: Contextual Chunks (Preprocessing)

### 6.1 Problem: Chunks Lose Document Context

**Current Issue**:
```
Chunk text: "He was confident of his powers."
```
**Missing**: Who is "he"? What book? What chapter?

**Result**: Embedding doesn't capture full semantic meaning

### 6.2 Solution: Add Context to Each Chunk

```
Original: "He was confident of his powers."

Contextualized:
"Document: Sir Robert's Fortune (Novel)
Chapter 3: The Uncle's Challenge
Context: Sir Robert discussing his plan to inherit his uncle's fortune

Text: He was confident of his powers of cheating the uncle, and managing the inheritance successfully."
```

### 6.3 Implementation Plan

**File**: `backend/backend/services/contextual_chunker.py` (new)

```python
from typing import List, Dict

class ContextualChunker:
    """Add document/chapter context to chunks for better embeddings"""

    async def enrich_chunks(
        self,
        chunks: List[str],
        document_metadata: Dict
    ) -> List[str]:
        """
        Add contextual information to each chunk

        Args:
            chunks: Raw text chunks
            document_metadata: {
                'title': 'Sir Robert's Fortune',
                'author': 'Jane Smith',
                'chapter': 'Chapter 3',
                'section': 'The Uncle's Challenge'
            }

        Returns:
            Enriched chunks with context prepended
        """
        enriched = []

        for chunk in chunks:
            context_prefix = f"""Document: {document_metadata.get('title', 'Unknown')}
Author: {document_metadata.get('author', 'Unknown')}
Chapter: {document_metadata.get('chapter', 'N/A')}

Text: """

            enriched_chunk = context_prefix + chunk
            enriched.append(enriched_chunk)

        return enriched
```

**Integration**: Modify document upload/indexing pipeline to use `ContextualChunker`

**Configuration** (.env):
```bash
ENABLE_CONTEXTUAL_CHUNKS=true
CONTEXT_PREFIX_FORMAT=detailed  # minimal, detailed, full
```

**Estimated Impact**:
- +10-15% accuracy on pronoun resolution and ambiguous references
- Slightly larger embeddings (acceptable for quality gain)

---

## 7. Priority 6: Meta-Learning for Query Classification

### 7.1 Problem: One-Size-Fits-All Retrieval

**Current**: All queries use same retrieval parameters
- "Who wrote X?" → Same vector_limit, reranker mode
- "Explain the plot of X" → Same parameters

**Issue**: Different query types need different strategies

### 7.2 Solution: Classify Query Type → Apply Optimal Strategy

```
Query → [Classifier] → "Author Query" → Strategy: {
                                            vector_limit: 5,
                                            filters: {'metadata.field': 'author'},
                                            reranker: 'fallback'
                                        }

Query → [Classifier] → "Plot Summary" → Strategy: {
                                            vector_limit: 30,
                                            filters: {'metadata.type': 'chapter'},
                                            reranker: 'primary'
                                        }
```

### 7.3 Implementation Plan

**File**: `backend/backend/services/query_classifier.py` (new)

```python
from typing import Dict, Literal
import re

QueryType = Literal[
    "author_query",
    "plot_summary",
    "character_analysis",
    "relationship_query",
    "quote_search",
    "general"
]

class QueryClassifier:
    """Classify query type and return optimal retrieval strategy"""

    def __init__(self):
        self.patterns = {
            "author_query": [
                r"who wrote",
                r"who is the author",
                r"written by",
                r"author of"
            ],
            "plot_summary": [
                r"what (is|was) the (plot|story)",
                r"summarize",
                r"what happens in"
            ],
            "character_analysis": [
                r"who is \w+",
                r"character of \w+",
                r"describe \w+"
            ],
            "relationship_query": [
                r"relationship between",
                r"how (are|were) \w+ and \w+ related"
            ],
            "quote_search": [
                r"\".*\"",  # Quoted text
                r"said",
                r"quote"
            ]
        }

        self.strategies = {
            "author_query": {
                "vector_limit": 5,
                "filters": {"metadata_field": "author"},
                "reranker_mode": "fallback",
                "top_k": 3
            },
            "plot_summary": {
                "vector_limit": 30,
                "filters": {"metadata_type": "chapter"},
                "reranker_mode": "primary",
                "top_k": 20
            },
            "character_analysis": {
                "vector_limit": 20,
                "filters": None,
                "reranker_mode": "primary",
                "top_k": 15
            },
            "relationship_query": {
                "vector_limit": 25,
                "filters": None,
                "reranker_mode": "primary",
                "top_k": 20,
                "use_graph_rag": True  # Future feature
            },
            "quote_search": {
                "vector_limit": 50,
                "filters": None,
                "reranker_mode": "primary",
                "top_k": 10,
                "use_bm25": True  # Exact keyword matching
            },
            "general": {
                "vector_limit": 20,
                "filters": None,
                "reranker_mode": "auto",
                "top_k": 10
            }
        }

    def classify(self, query: str) -> QueryType:
        """Classify query into predefined types"""
        query_lower = query.lower()

        for query_type, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return query_type

        return "general"

    def get_strategy(self, query: str) -> Dict:
        """Get optimal retrieval strategy for query"""
        query_type = self.classify(query)
        return self.strategies[query_type]
```

**Integration in `rag_pipeline.py`**:

```python
# Line ~280
classifier = QueryClassifier()
strategy = classifier.get_strategy(question)

# Apply strategy
vector_limit = strategy['vector_limit']
reranker_mode = strategy['reranker_mode']
top_k = strategy['top_k']

# Retrieve with optimized parameters
results = await self.retrieve(
    question,
    vector_limit=vector_limit,
    reranker_mode=reranker_mode,
    top_k=top_k
)
```

**Estimated Impact**:
- +20% accuracy on specialized query types
- 40-60% faster for simple queries (author, quote search)

---

## 8. Long-Term Advanced Features (1+ months)

### 8.1 Graph RAG for Relationship Queries

**Use Case**: "How are Sir Robert and Uncle Robert related?"

**Architecture**:
```
Documents → [Entity Extraction] → Entities: [Sir Robert, Uncle Robert, Fortune, Cheating]
         ↓
         → [Relationship Extraction] → Graph:
                Sir Robert --[nephew_of]--> Uncle Robert
                Sir Robert --[seeks]--> Fortune
                Sir Robert --[plans]--> Cheating
         ↓
Query → [Graph Traversal] → Path: Sir Robert → nephew_of → Uncle Robert
                                               → plans → Cheating
         ↓
         → [LLM Synthesis] → "Sir Robert is the nephew of Uncle Robert and plans to cheat him to gain his fortune"
```

**Implementation**: Use Neo4j or NetworkX + Cypher queries

### 8.2 RL-Based Policy Learning

**Concept**: Learn optimal retrieval strategies from user feedback

```
State: Query features (length, entities, complexity)
Action: Retrieval parameters (vector_limit, top_k, reranker_mode)
Reward: User satisfaction (implicit: click, dwell time / explicit: thumbs up/down)

Policy Network: State → Action → Expected Reward
```

**Implementation**: Use PPO (Proximal Policy Optimization) or DQN

### 8.3 Implicit Feedback Collection

**Metrics to Track**:
- Query → Answer latency
- User clicked citations (which sources were most useful?)
- Re-query patterns (did user rephrase? Indicates poor answer)
- Dwell time on answer page

**Use Case**: Retrain reranker model with implicit feedback as relevance labels

---

## 9. Implementation Timeline

### Week 1-2: Immediate Improvements (Priority 1-2)
- ✅ **Already Done**: Model name display, vector limits, score thresholds, reasoning transparency
- [ ] **Day 1-3**: Implement BM25 hybrid search
- [ ] **Day 4-7**: Implement query strategy caching
- [ ] **Day 8-10**: Integration testing
- [ ] **Day 11-14**: Performance benchmarking

**Expected Gains**: +20% accuracy, 90% token savings on cached queries

### Week 3-4: Advanced Retrieval (Priority 3-4)
- [ ] **Day 15-20**: Implement Self-RAG with confidence thresholds
- [ ] **Day 21-25**: Implement incremental context for iterations
- [ ] **Day 26-28**: End-to-end testing with complex queries

**Expected Gains**: +30% accuracy on complex queries, 60% token reduction in iterations

### Week 5-6: Preprocessing & Classification (Priority 5-6)
- [ ] **Day 29-33**: Implement contextual chunk enrichment
- [ ] **Day 34-38**: Implement query classifier with meta-learning
- [ ] **Day 39-42**: Reindex existing documents with contextual chunks

**Expected Gains**: +15% accuracy on ambiguous queries, 40% faster on specialized queries

### Month 2-3: Long-Term Features (Optional)
- [ ] **Week 7-10**: Graph RAG for relationship queries
- [ ] **Week 11-12**: RL-based policy learning infrastructure
- [ ] **Ongoing**: Implicit feedback collection and model retraining

---

## 10. Success Metrics

### Accuracy Metrics
- **Current**: ~70% answer accuracy on complex book queries
- **Target (Week 2)**: 85% accuracy with hybrid search + caching
- **Target (Week 4)**: 90% accuracy with Self-RAG
- **Target (Week 6)**: 92% accuracy with contextual chunks

### Latency Metrics
- **Current**: ~800ms average response time
- **Target (Week 2)**: 500ms for cached queries, 900ms for new queries
- **Target (Week 4)**: 1.2s for simple queries, 2.5s for iterative Self-RAG

### Token Efficiency
- **Current**: ~1500 tokens per query (avg)
- **Target (Week 2)**: 150 tokens for cached queries (90% reduction)
- **Target (Week 4)**: 800 tokens for iterative queries (60% reduction vs naive iteration)

### User Satisfaction
- **Metric**: Net Promoter Score (NPS) from user feedback
- **Target**: NPS > 8/10 for complex book queries

---

## 11. Configuration Management

### Environment Variables (.env)

```bash
# === Hybrid Search ===
ENABLE_HYBRID_SEARCH=true
HYBRID_ALPHA=0.7  # 70% vector, 30% BM25
BM25_TOP_K=25

# === Query Strategy Caching ===
ENABLE_QUERY_CACHE=true
QUERY_CACHE_SIMILARITY_THRESHOLD=0.85
QUERY_CACHE_MAX_SIZE=1000

# === Self-RAG ===
ENABLE_SELF_RAG=true
SELF_RAG_CONFIDENCE_THRESHOLD=0.75
SELF_RAG_MAX_ITERATIONS=3

# === Contextual Chunks ===
ENABLE_CONTEXTUAL_CHUNKS=true
CONTEXT_PREFIX_FORMAT=detailed

# === Query Classification ===
ENABLE_QUERY_CLASSIFICATION=true
```

### API Endpoints

```
POST /api/rag/ask                  # Standard RAG (current)
POST /api/rag/ask-hybrid           # Hybrid search enabled
POST /api/rag/ask-iterative        # Self-RAG with iterations
POST /api/rag/ask-smart            # All features enabled (hybrid + self-RAG + caching)
```

---

## 12. Testing Strategy

### Unit Tests
- `tests/test_hybrid_retriever.py`: BM25 + vector fusion
- `tests/test_query_cache.py`: Cache hit/miss, similarity matching
- `tests/test_self_rag.py`: Iteration logic, confidence thresholds
- `tests/test_contextual_chunker.py`: Context enrichment

### Integration Tests
- `tests/test_rag_pipeline_end_to_end.py`: Full pipeline with all features
- `tests/test_token_efficiency.py`: Measure token usage reduction

### Benchmark Queries (Complex Book Questions)
1. "Sir Robert's fortune a novel, for what purpose he was confident of his own powers of cheating the uncle, and managing?"
2. "Who wrote Pride and Prejudice and what year was it published?"
3. "Describe the relationship between Elizabeth Bennet and Mr. Darcy"
4. "What is the main theme of Moby Dick?"
5. "Find the quote 'It was the best of times, it was the worst of times'"

---

## 13. Risk Mitigation

### Risk 1: BM25 Index Build Time
- **Mitigation**: Build index asynchronously during startup, cache to disk
- **Fallback**: Use vector-only search if BM25 not ready

### Risk 2: Query Cache Memory Usage
- **Mitigation**: LRU eviction policy, max 1000 queries cached
- **Fallback**: Redis/Memcached for distributed caching

### Risk 3: Self-RAG Latency Explosion
- **Mitigation**: Hard limit of 3 iterations, timeout after 5 seconds
- **Fallback**: Return best answer so far, indicate "low confidence"

### Risk 4: Contextual Chunks Increase Storage
- **Mitigation**: Store raw chunks + context template (don't duplicate)
- **Fallback**: Enable/disable via feature flag

---

## 14. Monitoring & Observability

### Prometheus Metrics (Add to existing)
```python
# Hybrid search metrics
hybrid_search_duration = Histogram('rag_hybrid_search_duration_seconds')
bm25_score_distribution = Histogram('rag_bm25_score_distribution')
vector_score_distribution = Histogram('rag_vector_score_distribution')

# Cache metrics
cache_hit_rate = Gauge('rag_cache_hit_rate')
cache_size = Gauge('rag_cache_size')

# Self-RAG metrics
self_rag_iterations = Histogram('rag_self_rag_iterations')
self_rag_confidence_progression = Histogram('rag_confidence_by_iteration')
```

### Grafana Dashboards
- **RAG Accuracy Dashboard**: Precision@K, Recall@K, MRR
- **Token Efficiency Dashboard**: Tokens per query, cache savings
- **Latency Dashboard**: P50/P95/P99 latencies by query type

---

## 15. Documentation for Developers

### README Updates
- Add section: "Advanced RAG Features"
- Document API parameters: `use_hybrid`, `enable_self_rag`, `cached`
- Provide example curl commands for each endpoint

### API Documentation (Swagger/OpenAPI)
- Update `RAGRequest` schema with new optional fields
- Document response fields: `iterations_used`, `cache_hit`, `query_type`

### Architecture Diagram
```
User Query
    ↓
[Query Classifier] → Determine query type
    ↓
[Strategy Cache] → Check for cached strategy
    ↓
[Hybrid Retriever] → BM25 + Vector fusion
    ↓
[Reranker] → Cross-encoder scoring
    ↓
[Self-RAG Controller] → Iterative retrieval if needed
    ↓
[LLM Generator] → Incremental context prompting
    ↓
[Response] → Answer + confidence + metadata
```

---

## 16. Conclusion

This comprehensive RAG strategy synthesizes all discussed improvements into a practical, phased implementation plan. The prioritization balances **impact** (accuracy, token efficiency) with **complexity** (implementation time).

### Key Takeaways:
1. **Hybrid search** addresses keyword-semantic gap (+20% accuracy)
2. **Query caching** provides 90% token savings for repeated queries
3. **Self-RAG** enables iterative refinement for complex queries (+30% accuracy)
4. **Incremental context** optimizes multi-turn interactions (60% token reduction)
5. **Contextual chunks** improve embedding quality for ambiguous text (+15% accuracy)
6. **Query classification** applies optimal strategies per query type (40% faster)

### Next Steps:
1. Review and approve this strategy document
2. Begin Week 1 implementation (BM25 hybrid search)
3. Set up monitoring infrastructure (Prometheus/Grafana)
4. Conduct weekly benchmarking against test query set
5. Iterate based on real-world performance data

---

**Document Version**: 1.0
**Date**: 2025-11-26
**Author**: AI-Louie Development Team
**Status**: Ready for Implementation
