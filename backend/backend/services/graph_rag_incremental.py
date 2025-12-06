"""
Incremental Graph RAG with Just-In-Time (JIT) Entity Building

This module implements a knowledge graph-based RAG system that builds
the graph incrementally based on actual queries, rather than processing
all data upfront.

Key Features:
- Zero initial cost (no upfront graph building)
- JIT entity and relationship extraction
- Query-driven graph growth
- Automatic caching and reuse
- Hybrid retrieval (graph + vector)
"""

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime
import json
import re
import networkx as nx
from dataclasses import dataclass, asdict
import os

from openai import AsyncOpenAI
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Entity in the knowledge graph."""
    name: str
    type: str  # person, place, concept, skill, tool, etc.
    source_chunks: List[str]  # Chunk IDs where this entity appears
    attributes: Dict[str, Any] = None

    def __post_init__(self):
        if self.attributes is None:
            self.attributes = {}


@dataclass
class Relationship:
    """Relationship between entities."""
    source: str  # Entity name
    target: str  # Entity name
    relation_type: str  # e.g., "uses", "teaches", "requires", "related_to"
    evidence: List[str]  # Source chunks supporting this relationship
    confidence: float = 1.0
    attributes: Dict[str, Any] = None

    def __post_init__(self):
        if self.attributes is None:
            self.attributes = {}


@dataclass
class GraphStats:
    """Statistics about the knowledge graph."""
    num_entities: int
    num_relationships: int
    num_entity_types: Dict[str, int]
    coverage_chunks: int  # Number of chunks processed
    last_updated: str


class IncrementalGraphRAG:
    """
    Incremental Graph RAG with JIT Building.

    Flow:
    1. Extract entities from query
    2. Check if entities exist in graph
    3. If missing: JIT build them from Qdrant
    4. Query graph for relationships
    5. Combine graph context with vector retrieval
    6. Generate answer with LLM
    """

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        qdrant_client: QdrantClient,
        collection_name: str = "assessment_docs_minilm",
        extraction_model: str = "gpt-4o-mini",  # Changed from gpt-4o-mini to match API key access
        generation_model: str = "gpt-4o-mini",  # High-quality for answers
        max_jit_chunks: int = 20,  # Max chunks to process during JIT build (lower to reduce first-hit latency)
    ):
        self.openai_client = openai_client
        self.qdrant_client = qdrant_client
        self.collection_name = collection_name
        self.extraction_model = extraction_model
        self.generation_model = generation_model
        # Allow tuning via environment
        self.max_jit_chunks = int(os.getenv("GRAPH_JIT_MAX_CHUNKS", max_jit_chunks))
        # Smaller batches but higher timeout to reduce timeouts
        self.jit_batch_size = int(os.getenv("GRAPH_JIT_BATCH_SIZE", "4"))
        self.jit_batch_timeout = float(os.getenv("GRAPH_JIT_BATCH_TIMEOUT", "30"))  # seconds per batch

        # In-memory knowledge graph
        self.graph = nx.DiGraph()

        # Entity cache: name -> Entity object
        self.entities: Dict[str, Entity] = {}

        # Track which chunks have been processed
        self.processed_chunks: Set[str] = set()

        # Simple memo to avoid re-building the same entity set repeatedly
        self.jit_cache: Dict[Tuple[str, ...], Dict[str, Any]] = {}

        # Statistics
        self.stats = GraphStats(
            num_entities=0,
            num_relationships=0,
            num_entity_types={},
            coverage_chunks=0,
            last_updated=datetime.utcnow().isoformat()
        )

        logger.info("IncrementalGraphRAG initialized with JIT building")

    async def answer_question(
        self,
        question: str,
        top_k: int = 5,
        max_hops: int = 2,
        enable_vector_retrieval: bool = True,
    ) -> Dict[str, Any]:
        """
        Answer a question using incremental Graph RAG.

        Args:
            question: User's question
            top_k: Number of chunks for vector retrieval
            max_hops: Max graph traversal distance
            enable_vector_retrieval: Whether to combine with vector search

        Returns:
            Answer with graph context, timings, and statistics
        """
        start_time = time.time()
        timings = {}

        # Initialize token tracking for all LLM calls
        total_tokens = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        total_cost_usd = 0.0

        logger.info(f"Graph RAG Question: {question}")
        logger.info(f"Graph RAG settings: max_jit_chunks={self.max_jit_chunks}, batch_size={self.jit_batch_size}, batch_timeout={self.jit_batch_timeout}s")

        # Step 1: Extract entities from query
        t0 = time.time()
        query_entities, entity_extraction_tokens, entity_extraction_cost = await self.extract_query_entities(question)
        timings['entity_extraction_ms'] = (time.time() - t0) * 1000
        # Accumulate tokens from entity extraction
        if entity_extraction_tokens:
            total_tokens['prompt_tokens'] += entity_extraction_tokens.get('prompt_tokens', 0)
            total_tokens['completion_tokens'] += entity_extraction_tokens.get('completion_tokens', 0)
            total_tokens['total_tokens'] += entity_extraction_tokens.get('total_tokens', 0)
            total_cost_usd += entity_extraction_cost
        logger.info(f"Extracted {len(query_entities)} query entities: {query_entities}")

        # Step 2: Check graph coverage
        t0 = time.time()
        existing_entities, missing_entities = self.check_entities_in_graph(query_entities)
        timings['graph_check_ms'] = (time.time() - t0) * 1000
        logger.info(f"Graph coverage: {len(existing_entities)} exist, {len(missing_entities)} missing")

        # Step 3: JIT build missing entities
        jit_stats = None
        if missing_entities:
            t0 = time.time()
            jit_stats = await self.jit_build_entities(missing_entities, question)
            timings['jit_build_ms'] = (time.time() - t0) * 1000
            # Accumulate tokens from JIT building
            if jit_stats and jit_stats.get('token_usage'):
                jit_tokens = jit_stats['token_usage']
                total_tokens['prompt_tokens'] += jit_tokens.get('prompt_tokens', 0)
                total_tokens['completion_tokens'] += jit_tokens.get('completion_tokens', 0)
                total_tokens['total_tokens'] += jit_tokens.get('total_tokens', 0)
                total_cost_usd += jit_stats.get('token_cost_usd', 0.0)
            logger.info(f"JIT built {jit_stats['entities_added']} entities, "
                       f"{jit_stats['relationships_added']} relationships "
                       f"from {jit_stats['chunks_processed']} chunks")
        else:
            timings['jit_build_ms'] = 0
            logger.info("All entities exist in graph - using cache")

        # Step 4: Query graph for relationships
        t0 = time.time()
        graph_context = self.query_subgraph(query_entities, max_hops=max_hops)
        timings['graph_query_ms'] = (time.time() - t0) * 1000
        logger.info(f"Graph query returned {graph_context['num_entities']} entities, "
                   f"{graph_context['num_relationships']} relationships")

        # Step 5: Optional vector retrieval for additional context
        vector_chunks = []
        if enable_vector_retrieval:
            t0 = time.time()
            vector_chunks = await self.vector_retrieve(question, top_k=top_k)
            timings['vector_retrieval_ms'] = (time.time() - t0) * 1000
            logger.info(f"Vector retrieval returned {len(vector_chunks)} chunks")
        else:
            timings['vector_retrieval_ms'] = 0

        # Fallback: if graph is empty, seed with query entities for UI visibility
        if graph_context['num_entities'] == 0:
            minimal_entities = [
                {'name': ent, 'type': 'character', 'num_sources': 0}
                for ent in query_entities
            ]
            graph_context = {
                'entities': minimal_entities,
                'relationships': [],
                'num_entities': len(minimal_entities),
                'num_relationships': 0
            }

        # Step 6: Generate answer with LLM
        t0 = time.time()
        answer_result = await self.generate_answer(
            question=question,
            graph_context=graph_context,
            vector_chunks=vector_chunks
        )
        timings['answer_generation_ms'] = (time.time() - t0) * 1000
        # Accumulate tokens from answer generation
        if answer_result.get('token_usage'):
            answer_tokens = answer_result['token_usage']
            total_tokens['prompt_tokens'] += answer_tokens.get('prompt_tokens', 0)
            total_tokens['completion_tokens'] += answer_tokens.get('completion_tokens', 0)
            total_tokens['total_tokens'] += answer_tokens.get('total_tokens', 0)
            total_cost_usd += answer_result.get('token_cost_usd', 0.0)

        # Total time
        total_time_ms = (time.time() - start_time) * 1000
        timings['total_ms'] = total_time_ms
        # Fill timing fields expected by UI
        # Graph RAG doesn't use traditional embedding/reranking, so report JIT and graph query times
        timings['embed_ms'] = timings.get('entity_extraction_ms', 0.0)  # Entity extraction is like embedding
        timings['vector_ms'] = timings.get('vector_retrieval_ms', 0.0)
        timings['candidate_prep_ms'] = timings.get('jit_build_ms', 0.0) + timings.get('graph_check_ms', 0.0)  # JIT build + graph check
        timings['rerank_ms'] = timings.get('graph_query_ms', 0.0)  # Graph query is like reranking
        timings['llm_ms'] = timings.get('answer_generation_ms', 0.0)

        # Build response with accumulated tokens from ALL LLM calls
        response = {
            'answer': answer_result['answer'],
            'graph_context': {
                'entities': graph_context['entities'],
                'relationships': graph_context['relationships'],
                'num_entities': graph_context['num_entities'],
                'num_relationships': graph_context['num_relationships'],
            },
            'jit_stats': jit_stats,
            'graph_stats': asdict(self.stats),
            'timings': {**timings, 'graph_context': graph_context},
            'token_usage': total_tokens,  # FIXED: Use accumulated tokens from ALL LLM calls
            'token_cost_usd': total_cost_usd,  # FIXED: Use accumulated cost from ALL LLM calls
            'query_entities': query_entities,
            'cache_hit': len(missing_entities) == 0,
        }

        logger.info(f"Graph RAG completed in {total_time_ms:.1f}ms "
                   f"(cache_hit={response['cache_hit']})")

        return response

    async def extract_query_entities(self, question: str) -> Tuple[List[str], Dict[str, int], float]:
        """
        Extract key entities from the user's question.

        Uses LLM to identify entities that should be searched in the graph.

        Returns:
            Tuple of (entities, token_usage, token_cost_usd)
        """
        prompt = f"""Extract key entities from this question that would be useful for graph-based knowledge retrieval.

Question: {question}

Identify specific entities like:
- People (e.g., "Sir Robert", "Uncle")
- Places (e.g., "London", "workshop")
- Concepts (e.g., "woodworking", "safety", "fortune")
- Skills (e.g., "carpentry", "joinery")
- Tools (e.g., "hammer", "saw")
- Events (e.g., "cheating", "managing")

Return a JSON object with an "entities" array containing entity names (lowercase, singular form):
{{"entities": ["entity1", "entity2", ...]}}

Keep it concise - maximum 5 entities.
"""

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.extraction_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
                response_format={"type": "json_object"},  # Enforce JSON output
            )

            content = response.choices[0].message.content.strip()

            # Parse JSON - handle both array and object format
            parsed = json.loads(content)
            if isinstance(parsed, list):
                entities = parsed
            elif isinstance(parsed, dict) and 'entities' in parsed:
                entities = parsed['entities']
            else:
                # Fallback: extract any array from the object
                entities = list(parsed.values())[0] if parsed else []

            # Normalize: lowercase, strip whitespace
            entities = [e.lower().strip() for e in entities if e.strip()]

            # Calculate token usage and cost
            from backend.services.token_counter import get_token_counter, TokenUsage
            token_counter = get_token_counter()
            actual_model = getattr(response, 'model', self.extraction_model)
            token_usage = {
                'prompt_tokens': response.usage.prompt_tokens,
                'completion_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens,
            }
            usage_obj = TokenUsage(
                model=actual_model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                timestamp=datetime.now(),
            )
            cost_usd = token_counter.estimate_cost(usage_obj)

            return entities[:5], token_usage, cost_usd  # Max 5 entities

        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            # Fallback: simple keyword extraction
            # Extract nouns and important words
            words = re.findall(r'\b[a-z]{3,}\b', question.lower())
            # Remove common stop words
            stop_words = {'what', 'how', 'when', 'where', 'who', 'which', 'does', 'are', 'the', 'and', 'for'}
            entities = [w for w in words if w not in stop_words]
            return entities[:5], {}, 0.0

    def check_entities_in_graph(self, entity_names: List[str]) -> Tuple[List[str], List[str]]:
        """
        Check which entities exist in the graph.

        Returns:
            (existing_entities, missing_entities)
        """
        existing = []
        missing = []

        for name in entity_names:
            if name in self.entities:
                existing.append(name)
            else:
                missing.append(name)

        return existing, missing

    async def jit_build_entities(
        self,
        entity_names: List[str],
        context_query: str
    ) -> Dict[str, Any]:
        """
        Just-In-Time build: Extract entities and relationships for missing entities.

        Process:
        1. Search Qdrant for chunks mentioning these entities
        2. Extract entities and relationships from those chunks (BATCHED & PARALLEL)
        3. Add to graph

        Args:
            entity_names: List of entity names to build
            context_query: Original question for context-aware retrieval

        Returns:
            Statistics about what was built
        """
        logger.info(f"JIT building entities (person-focus): {entity_names}")

        # Cache key for this entity set
        cache_key = tuple(sorted(entity_names))
        if cache_key in self.jit_cache:
            logger.info("JIT cache hit for entity set; skipping rebuild")
            return self.jit_cache[cache_key]

        entities_added = 0
        relationships_added = 0
        chunks_processed = 0

        # Track token usage from JIT LLM calls
        jit_tokens = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        jit_cost_usd = 0.0

        # Search Qdrant for relevant chunks
        search_query = f"{context_query} {' '.join(entity_names)}"

        try:
            # Generate embedding for search query
            from backend.services.rag_pipeline import _embed_texts
            query_embedding = (await _embed_texts([search_query]))[0]

            # Retrieve chunks from Qdrant
            search_results = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=self.max_jit_chunks,
                with_payload=["text", "content", "source", "document_id"],
            )

            logger.info(f"Found {len(search_results)} chunks for JIT building")
            if not search_results:
                logger.warning("JIT build: Qdrant search returned 0 results")
                return {
                    'entities_added': 0,
                    'relationships_added': 0,
                    'chunks_processed': 0,
                    'note': 'No search results for JIT build'
                }

            # Filter unprocessed chunks
            unprocessed_chunks = []
            for result in search_results:
                chunk_id = result.id
                if chunk_id in self.processed_chunks:
                    continue

                payload = result.payload or {}
                chunk_content = payload.get('text') or payload.get('content', '')
                chunk_source = payload.get('source', 'unknown')

                if chunk_content:
                    unprocessed_chunks.append({
                        'id': chunk_id,
                        'content': chunk_content,
                        'source': chunk_source
                    })

            logger.info(f"JIT build: {len(unprocessed_chunks)} chunks remaining after dedup")
            if not unprocessed_chunks:
                logger.info("All chunks already processed (cache hit)")
                return {
                    'entities_added': 0,
                    'relationships_added': 0,
                    'chunks_processed': 0,
                    'note': 'All candidate chunks were already processed'
                }

            # Hard cap in case backend limit differs
            unprocessed_chunks = unprocessed_chunks[: self.max_jit_chunks]
            fallback_candidates = unprocessed_chunks[:5]  # keep a few for single-chunk fallback

            logger.info(f"Processing {len(unprocessed_chunks)} new chunks with batch extraction")

            # **OPTIMIZATION: Batch extract entities in parallel**
            batch_size = max(1, self.jit_batch_size)
            batches = [unprocessed_chunks[i:i+batch_size] for i in range(0, len(unprocessed_chunks), batch_size)]

            # Run batch extractions in parallel
            async def _run_batch(batch):
                logger.info(f"Batch extraction start: size={len(batch)} timeout={self.jit_batch_timeout}s")
                try:
                    res = await asyncio.wait_for(
                        self.batch_extract_entities_and_relationships(batch),
                        timeout=self.jit_batch_timeout
                    )
                    logger.info(f"Batch extraction done: size={len(batch)}")
                    return res
                except asyncio.TimeoutError:
                    logger.warning(f"Batch extraction timeout after {self.jit_batch_timeout}s (size={len(batch)})")
                    return []

            extraction_tasks = [_run_batch(batch) for batch in batches]
            batch_results = await asyncio.gather(*extraction_tasks, return_exceptions=True)

            # Merge results from all batches
            for batch_idx, batch_result in enumerate(batch_results):
                if isinstance(batch_result, Exception):
                    logger.error(f"Batch {batch_idx} extraction failed: {batch_result}")
                    continue
                if not batch_result:
                    logger.warning(f"Batch {batch_idx} returned empty result")
                    continue

                # Log batch extraction stats
                total_ents = sum(len(x.get('entities', [])) for x in batch_result)
                total_rels = sum(len(x.get('relationships', [])) for x in batch_result)
                logger.info(f"Batch {batch_idx} extracted entities={total_ents}, relationships={total_rels}")

                # Add extracted entities and relationships to graph
                for chunk_data in batch_result:
                    chunk_id = chunk_data['chunk_id']

                    # Add entities
                    for entity in chunk_data['entities']:
                        if entity['name'] not in self.entities:
                            self.add_entity(
                                name=entity['name'],
                                entity_type=entity['type'],
                                chunk_id=chunk_id
                            )
                            entities_added += 1
                        else:
                            # Update existing entity
                            if chunk_id not in self.entities[entity['name']].source_chunks:
                                self.entities[entity['name']].source_chunks.append(chunk_id)

                    # Add relationships
                    for rel in chunk_data['relationships']:
                        self.add_relationship(
                            source=rel['source'],
                            target=rel['target'],
                            relation_type=rel['relation'],
                            chunk_id=chunk_id
                        )
                        relationships_added += 1

                    self.processed_chunks.add(chunk_id)
                    chunks_processed += 1

            # If nothing extracted, try a lightweight single-chunk fallback on a few items
            if entities_added == 0 and relationships_added == 0 and fallback_candidates:
                logger.info(f"No entities from batch; running single-chunk fallback on {len(fallback_candidates)} chunk(s)")
                for fc in fallback_candidates:
                    try:
                        single = await self.extract_entities_and_relationships(
                            text=fc['content'],
                            chunk_id=fc['id'],
                            chunk_source=fc.get('source', 'unknown')
                        )
                        # Log fallback stats
                        logger.info(
                            f"Fallback single chunk result: entities={len(single.get('entities', []))}, "
                            f"relationships={len(single.get('relationships', []))}"
                        )
                        if single['entities'] or single['relationships']:
                            for entity in single['entities']:
                                if entity['name'] not in self.entities:
                                    self.add_entity(entity['name'], entity.get('type', 'character'), fc['id'])
                                    entities_added += 1
                                else:
                                    if fc['id'] not in self.entities[entity['name']].source_chunks:
                                        self.entities[entity['name']].source_chunks.append(fc['id'])
                            for rel in single['relationships']:
                                self.add_relationship(rel['source'], rel['target'], rel.get('relation', 'related_to'), fc['id'])
                                relationships_added += 1
                            self.processed_chunks.add(fc['id'])
                            chunks_processed += 1
                    except Exception as e:
                        logger.warning(f"Fallback single-chunk extraction failed: {e}")

            # Update stats
            self.stats.num_entities = len(self.entities)
            self.stats.num_relationships = self.graph.number_of_edges()
            self.stats.coverage_chunks = len(self.processed_chunks)
            self.stats.last_updated = datetime.utcnow().isoformat()

            logger.info(f"✅ Batch extraction completed: {entities_added} entities, "
                       f"{relationships_added} relationships from {chunks_processed} chunks")

            result = {
                'entities_added': entities_added,
                'relationships_added': relationships_added,
                'chunks_processed': chunks_processed,
                'token_usage': jit_tokens,  # Add token usage tracking
                'token_cost_usd': jit_cost_usd,  # Add cost tracking
            }
            # Memoize result for this entity set
            self.jit_cache[cache_key] = result

            return result

        except Exception as e:
            logger.error(f"JIT build failed: {e}")
            return {
                'entities_added': 0,
                'relationships_added': 0,
                'chunks_processed': 0,
                'token_usage': {},
                'token_cost_usd': 0.0,
                'error': str(e)
            }

    async def batch_extract_entities_and_relationships(
        self,
        chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract entities and relationships from multiple chunks in ONE LLM call.

        Args:
            chunks: List of chunk dicts with 'id', 'content', 'source'

        Returns:
            List of extraction results for each chunk
        """
        if not chunks:
            return []

        logger.info(f"LLM batch_extract start: {len(chunks)} chunks")
        # Build batch prompt with all chunks
        chunk_texts = []
        for i, chunk in enumerate(chunks):
            content = chunk['content'][:1000]  # Limit to 1000 chars per chunk
            chunk_texts.append(f"[Chunk {i+1}]\n{content}\n")

        combined_text = "\n".join(chunk_texts)

        prompt = f"""Extract characters / people / named roles and the relationships between them from multiple text chunks.

{combined_text}

For EACH chunk, extract:
1) Entities: characters/people/roles (e.g., "sir robert", "uncle", "king", "lady grey"). If a named entity (family, house, group) is directly tied to characters, include it. Ignore tools/places unless they are central to a character relationship.
2) Relationships: how these entities relate (family, colleague, ally, enemy, role-to-role, member-of, reports-to). Ignore object-only relations.

Respond with JSON array (one object per chunk):
[
  {{
    "chunk_index": 1,
    "entities": [
      {{"name": "entity_name", "type": "person|character|role"}},
      ...
    ],
    "relationships": [
      {{"source": "entity1", "target": "entity2", "relation": "family|ally|enemy|colleague|role|member_of|reports_to|related_to"}},
      ...
    ]
  }},
  ...
]

Entity names should be lowercase. Limit: max 10 entities and 15 relationships per chunk.
"""

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.extraction_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1500,  # Allow more room for entities/relationships
                response_format={"type": "json_object"},
            )
            logger.info(f"LLM batch_extract success: {len(chunks)} chunks")

            content = response.choices[0].message.content.strip()

            # Remove markdown if present
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            # Parse JSON - handle both array and object with results key
            parsed = json.loads(content)
            if isinstance(parsed, dict) and 'results' in parsed:
                results = parsed['results']
            elif isinstance(parsed, list):
                results = parsed
            else:
                # Fallback: assume it's a single result
                results = [parsed]

            # Map results back to chunks
            output = []
            for i, chunk in enumerate(chunks):
                # Find matching result by chunk_index or use position
                chunk_result = None
                for result in results:
                    if result.get('chunk_index') == i + 1:
                        chunk_result = result
                        break

                if not chunk_result and i < len(results):
                    chunk_result = results[i]

                if chunk_result:
                    # Validate and normalize (characters/roles)
                    validated_entities = []
                    for entity in chunk_result.get('entities', []):
                        if isinstance(entity, dict) and 'name' in entity:
                            entity['name'] = str(entity['name']).lower().strip()
                            if not entity.get('type'):
                                entity['type'] = 'character'
                            validated_entities.append(entity)

                    validated_relationships = []
                    for rel in chunk_result.get('relationships', []):
                        if isinstance(rel, dict) and 'source' in rel and 'target' in rel:
                            rel['source'] = str(rel['source']).lower().strip()
                            rel['target'] = str(rel['target']).lower().strip()
                            if 'relation' not in rel:
                                rel['relation'] = 'related_to'
                            validated_relationships.append(rel)

                    output.append({
                        'chunk_id': chunk['id'],
                        'entities': validated_entities,
                        'relationships': validated_relationships
                    })
                else:
                    # No result for this chunk
                    output.append({
                        'chunk_id': chunk['id'],
                        'entities': [],
                        'relationships': []
                    })

            return output

        except Exception as e:
            logger.error(f"Batch entity extraction failed: {e}")
            # Return empty results for all chunks
            return [
                {'chunk_id': chunk['id'], 'entities': [], 'relationships': []}
                for chunk in chunks
            ]

    async def extract_entities_and_relationships(
        self,
        text: str,
        chunk_id: str,
        chunk_source: str
    ) -> Dict[str, Any]:
        """
        Extract entities and relationships from text using LLM.

        Returns:
            {
                'entities': [{'name': str, 'type': str}, ...],
                'relationships': [{'source': str, 'target': str, 'relation': str}, ...]
            }
        """
        # Truncate very long text
        text_sample = text[:1500] if len(text) > 1500 else text

        prompt = f"""Extract characters / people / named roles and the relationships between them from this text.

Text: {text_sample}

Extract:
1) Entities: characters/people/roles (e.g., "sir robert", "uncle", "king", "lady grey"). If a named entity (family, house, group) is directly tied to characters, include it. Ignore tools/places unless they are central to a character relationship.
2) Relationships: how these entities relate (family, colleague, ally, enemy, role-to-role, member-of, reports-to). Ignore object-only relations.

Respond with JSON:
{{
  "entities": [
    {{"name": "entity_name", "type": "person|character|role"}},
    ...
  ],
  "relationships": [
    {{"source": "entity1", "target": "entity2", "relation": "family|ally|enemy|colleague|role|member_of|reports_to|related_to"}},
    ...
  ]
}}

Entity names should be lowercase and concise.
Limit: max 10 entities, max 15 relationships.
"""

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.extraction_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=800,
                response_format={"type": "json_object"},  # Enforce JSON output
            )

            content = response.choices[0].message.content.strip()

            # Remove markdown code blocks if present
            if content.startswith("```json"):
                content = content[7:]  # Remove ```json
            if content.startswith("```"):
                content = content[3:]  # Remove ```
            if content.endswith("```"):
                content = content[:-3]  # Remove trailing ```
            content = content.strip()

            # Log the raw response for debugging
            logger.debug(f"Entity extraction cleaned response for chunk {str(chunk_id)[:15]}: {content[:300]}")

            # Parse JSON
            result = json.loads(content)

            # Validate and normalize entity names
            validated_entities = []
            for entity in result.get('entities', []):
                if isinstance(entity, dict) and 'name' in entity:
                    entity['name'] = str(entity['name']).lower().strip()
                    if not entity.get('type'):
                        entity['type'] = 'character'
                    validated_entities.append(entity)
                else:
                    logger.warning(f"Skipping invalid entity: {entity}")

            # Validate and normalize relationships
            validated_relationships = []
            for rel in result.get('relationships', []):
                if isinstance(rel, dict) and 'source' in rel and 'target' in rel:
                    rel['source'] = str(rel['source']).lower().strip()
                    rel['target'] = str(rel['target']).lower().strip()
                    if 'relation' not in rel:
                        rel['relation'] = 'related_to'  # Default relation
                    validated_relationships.append(rel)
                else:
                    logger.warning(f"Skipping invalid relationship: {rel}")

            return {
                'entities': validated_entities,
                'relationships': validated_relationships
            }

        except Exception as e:
            logger.error(f"Entity/relationship extraction failed for chunk {chunk_id}: {e}")
            return {'entities': [], 'relationships': []}

    def add_entity(self, name: str, entity_type: str, chunk_id: str):
        """Add an entity to the graph."""
        if name not in self.entities:
            self.entities[name] = Entity(
                name=name,
                type=entity_type,
                source_chunks=[chunk_id]
            )
            self.graph.add_node(name, type=entity_type)

            # Update type stats
            if entity_type not in self.stats.num_entity_types:
                self.stats.num_entity_types[entity_type] = 0
            self.stats.num_entity_types[entity_type] += 1

            logger.debug(f"Added entity: {name} ({entity_type})")

    def add_relationship(
        self,
        source: str,
        target: str,
        relation_type: str,
        chunk_id: str,
        confidence: float = 1.0
    ):
        """Add a relationship to the graph."""
        # Ensure both entities exist (auto-create placeholders if missing)
        if source not in self.entities:
            self.add_entity(source, "character", chunk_id)
        if target not in self.entities:
            self.add_entity(target, "character", chunk_id)

        # Add edge
        if self.graph.has_edge(source, target):
            # Update existing edge
            edge_data = self.graph.edges[source, target]
            edge_data['evidence'].append(chunk_id)
            edge_data['confidence'] = max(edge_data['confidence'], confidence)
        else:
            # Create new edge
            self.graph.add_edge(
                source,
                target,
                relation=relation_type,
                evidence=[chunk_id],
                confidence=confidence
            )
            logger.debug(f"Added relationship: {source} --[{relation_type}]--> {target}")

    def query_subgraph(
        self,
        entity_names: List[str],
        max_hops: int = 2
    ) -> Dict[str, Any]:
        """
        Query the graph for a subgraph around the given entities.

        Args:
            entity_names: Starting entities
            max_hops: Maximum graph traversal distance

        Returns:
            Subgraph as entities and relationships
        """
        # Find all entities within max_hops
        subgraph_nodes = set()

        for entity in entity_names:
            if entity not in self.graph:
                continue

            # Add the entity itself
            subgraph_nodes.add(entity)

            # BFS to find connected nodes within max_hops
            visited = {entity}
            queue = [(entity, 0)]  # (node, distance)

            while queue:
                current, dist = queue.pop(0)

                if dist >= max_hops:
                    continue

                # Get neighbors (both directions)
                neighbors = set(self.graph.successors(current)) | set(self.graph.predecessors(current))

                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        subgraph_nodes.add(neighbor)
                        queue.append((neighbor, dist + 1))

        # Extract entities
        entities = []
        for node in subgraph_nodes:
            if node in self.entities:
                entity = self.entities[node]
                entities.append({
                    'name': entity.name,
                    'type': entity.type,
                    'num_sources': len(entity.source_chunks)
                })

        # Extract relationships
        relationships = []
        for source in subgraph_nodes:
            for target in subgraph_nodes:
                if self.graph.has_edge(source, target):
                    edge_data = self.graph.edges[source, target]
                    relationships.append({
                        'source': source,
                        'target': target,
                        'relation': edge_data.get('relation', 'related_to'),
                        'confidence': edge_data.get('confidence', 1.0),
                        'evidence_count': len(edge_data.get('evidence', []))
                    })

        return {
            'entities': entities,
            'relationships': relationships,
            'num_entities': len(entities),
            'num_relationships': len(relationships),
        }

    async def vector_retrieve(self, question: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve relevant chunks using vector search.

        This provides additional context beyond the graph.
        """
        try:
            # Generate embedding for query
            from backend.services.rag_pipeline import _embed_texts
            query_embedding = (await _embed_texts([question]))[0]

            search_results = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=top_k,
                with_payload=["text", "content", "source"],
            )

            chunks = []
            for result in search_results:
                payload = result.payload or {}
                chunks.append({
                    'text': payload.get('text') or payload.get('content', ''),
                    'source': payload.get('source', 'unknown'),
                    'score': result.score,
                })

            return chunks

        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return []

    async def generate_answer(
        self,
        question: str,
        graph_context: Dict[str, Any],
        vector_chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate an answer using graph context and optional vector chunks.
        """
        # Build context from graph
        graph_text = self._format_graph_context(graph_context)

        # Build context from vector chunks
        vector_text = ""
        if vector_chunks:
            vector_text = "\n\nAdditional Context from Documents:\n"
            for i, chunk in enumerate(vector_chunks, 1):
                vector_text += f"\n[{i}] {chunk['text'][:300]}...\n"

        # Combine contexts
        full_context = graph_text + vector_text

        # Generate answer
        prompt = f"""You are a helpful assistant answering questions based on a knowledge graph and supporting documents.

Question: {question}

{full_context}

Provide a clear, comprehensive answer based on the knowledge graph relationships and supporting documents.
If the graph shows relationships between entities, explain those connections.
"""

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.generation_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
            )

            answer = response.choices[0].message.content.strip()

            token_usage = {
                'prompt_tokens': response.usage.prompt_tokens,
                'completion_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens,
            }

            # Calculate cost using TokenCounter
            from backend.services.token_counter import get_token_counter, TokenUsage
            token_counter = get_token_counter()
            # Use the actual model name from OpenAI response (may include version suffix)
            # but fall back to self.generation_model if not available
            actual_model = getattr(response, 'model', self.generation_model)
            logger.info(f"Token cost calculation - using model: {actual_model} (response.model: {getattr(response, 'model', 'N/A')})")
            usage_obj = TokenUsage(
                model=actual_model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,  # FIXED: was using prompt_tokens twice
                total_tokens=response.usage.total_tokens,
                timestamp=datetime.now(),
            )
            cost_usd = token_counter.estimate_cost(usage_obj)

            return {
                'answer': answer,
                'token_usage': token_usage,
                'token_cost_usd': cost_usd,
            }

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return {
                'answer': f"I encountered an error generating the answer: {str(e)}",
                'token_usage': {},
                'token_cost_usd': 0.0,
            }

    def _format_graph_context(self, graph_context: Dict[str, Any]) -> str:
        """Format graph context for LLM prompt."""
        text = "Knowledge Graph Context:\n\n"

        # List entities
        text += "Entities:\n"
        for entity in graph_context['entities']:
            text += f"- {entity['name']} ({entity['type']})\n"

        # List relationships
        if graph_context['relationships']:
            text += "\nRelationships:\n"
            for rel in graph_context['relationships']:
                text += f"- {rel['source']} --[{rel['relation']}]--> {rel['target']} "
                text += f"(confidence: {rel['confidence']:.2f})\n"
        else:
            text += "\nNo direct relationships found in the graph.\n"

        return text

    def get_stats(self) -> Dict[str, Any]:
        """Get current graph statistics."""
        return asdict(self.stats)

    def clear_graph(self):
        """Clear the entire graph (for testing or reset)."""
        self.graph.clear()
        self.entities.clear()
        self.processed_chunks.clear()
        self.stats = GraphStats(
            num_entities=0,
            num_relationships=0,
            num_entity_types={},
            coverage_chunks=0,
            last_updated=datetime.utcnow().isoformat()
        )
        logger.info("Graph cleared")
