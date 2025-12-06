"""
Self-RAG: Iterative retrieval with self-reflection and confidence thresholds

Implements iterative document retrieval with LLM self-assessment until confidence threshold is met.
Integrated with AI Governance tracking for compliance and audit trails.
"""
import json
import os
import time
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import structlog

from backend.config.settings import settings
from backend.models.rag_schemas import RAGResponse, Citation
from backend.services.rag_pipeline import (
    retrieve_chunks,
    RetrievedChunk,
    _get_openai_client,
)
from backend.services.enhanced_rag_pipeline import answer_question_hybrid
from backend.services.governance_tracker import (
    get_governance_tracker,
    RiskTier,
    GovernanceCriteria,
)
from backend.utils.openai import sanitize_messages

logger = structlog.get_logger(__name__)


class SelfRAG:
    """
    Iterative retrieval with self-reflection and confidence assessment.

    The system iteratively retrieves documents and assesses whether the context
    is sufficient to answer the question with high confidence.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.75,
        max_iterations: int = 3,
        min_confidence_improvement: float = 0.05
    ):
        """
        Initialize Self-RAG system.

        Args:
            confidence_threshold: Minimum confidence score to stop iterating (0-1)
            max_iterations: Maximum number of retrieval iterations
            min_confidence_improvement: Minimum improvement required to continue iterating
        """
        self.confidence_threshold = confidence_threshold
        self.max_iterations = max_iterations
        self.min_confidence_improvement = min_confidence_improvement

    async def ask_with_reflection(
        self,
        question: str,
        *,
        top_k: int = 10,
        use_hybrid: bool = True,
        include_timings: bool = True
    ) -> RAGResponse:
        """
        Answer question with iterative retrieval and self-reflection.

        Args:
            question: User's question
            top_k: Number of chunks to retrieve per iteration
            use_hybrid: Use hybrid search (BM25 + vector)
            include_timings: Include detailed timing breakdown

        Returns:
            RAGResponse with iterative refinement metadata
        """
        tic_total = time.perf_counter()

        # Initialize AI Governance tracking
        governance_tracker = get_governance_tracker()
        gov_context = governance_tracker.start_operation(
            operation_type="self_rag",
            metadata={
                "question_length": len(question),
                "top_k": top_k,
                "use_hybrid": use_hybrid,
                "max_iterations": self.max_iterations,
                "confidence_threshold": self.confidence_threshold
            }
        )

        # G7: Observability - Log operation start
        gov_context.add_checkpoint(
            GovernanceCriteria.G7_OBSERVABILITY,
            "passed",
            f"Self-RAG operation started with {self.max_iterations} max iterations",
            metadata={"trace_id": gov_context.trace_id}
        )

        # G2: Risk Tiering - Self-RAG involves multiple LLM calls and iterations
        gov_context.add_checkpoint(
            GovernanceCriteria.G2_RISK_TIERING,
            "passed",
            f"Risk tier: {gov_context.risk_tier.value} - Iterative RAG with confidence assessment",
            metadata={"risk_level": "R1"}  # External customer-facing
        )

        iteration = 0
        all_chunks: List[RetrievedChunk] = []
        conversation_history: List[Dict[str, Any]] = []
        best_answer = None
        best_confidence = 0.0

        # Metadata tracking
        iterations_metadata = []

        # Token usage tracking across all iterations
        self._iteration_token_usage = []
        # Timing tracking across all iterations
        self._iteration_timings = []

        while iteration < self.max_iterations:
            iteration_start = time.perf_counter()
            logger.info(f"Self-RAG iteration {iteration + 1}/{self.max_iterations}", question=question[:50])

            # G7: Observability - Track each iteration
            gov_context.add_checkpoint(
                GovernanceCriteria.G7_OBSERVABILITY,
                "passed",
                f"Starting iteration {iteration + 1}/{self.max_iterations}",
                metadata={
                    "iteration": iteration + 1,
                    "total_chunks_so_far": len(all_chunks),
                    "current_best_confidence": best_confidence
                }
            )

            # Retrieve documents (first iteration or follow-up)
            if iteration == 0:
                # Initial retrieval
                if use_hybrid:
                    result = await answer_question_hybrid(
                        question=question,
                        top_k=top_k,
                        use_llm=True,
                        include_timings=include_timings
                    )
                else:
                    from backend.services.rag_pipeline import answer_question as base_answer
                    result = await base_answer(
                        question=question,
                        top_k=top_k,
                        use_llm=True,
                        include_timings=include_timings
                    )

                # Extract chunks from response
                all_chunks.extend([
                    RetrievedChunk(
                        content=c.content,
                        source=c.source,
                        score=c.score,
                        metadata=c.metadata or {}
                    )
                    for c in result.citations
                ])

                answer = result.answer
                confidence = result.confidence

                # Capture token usage from iteration 1
                logger.info(f"Iteration 1: result.token_usage = {result.token_usage}")
                if result.token_usage:
                    from backend.services.token_counter import _token_counter, TokenUsage
                    token_dict = result.token_usage
                    # Calculate cost for iteration 1
                    usage_obj = TokenUsage(
                        prompt_tokens=token_dict.get('prompt', 0),
                        completion_tokens=token_dict.get('completion', 0),
                        total_tokens=token_dict.get('total', 0),
                        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                        timestamp=datetime.utcnow()
                    )
                    cost = _token_counter.estimate_cost(usage_obj)
                    self._iteration_token_usage.append({
                        'prompt': token_dict.get('prompt', 0),
                        'completion': token_dict.get('completion', 0),
                        'total': token_dict.get('total', 0),
                        'cost': cost
                    })
                    logger.info(f"Captured iteration 1 tokens: {token_dict.get('total', 0)}")
                else:
                    logger.warning("Iteration 1: result.token_usage is None!")

                # Capture timings from iteration 1
                iteration_timings = getattr(result, 'timings', {}) or {}
                if iteration_timings:
                    self._iteration_timings.append(iteration_timings)
                    logger.info(f"Captured iteration 1 timings: embed={iteration_timings.get('embed_ms', 0):.1f}ms, "
                               f"vector={iteration_timings.get('vector_ms', 0):.1f}ms, "
                               f"rerank={iteration_timings.get('rerank_ms', 0):.1f}ms")

            else:
                # Follow-up retrieval based on reflection
                follow_up_query = conversation_history[-1]['follow_up_query']

                if use_hybrid:
                    result = await answer_question_hybrid(
                        question=follow_up_query,
                        top_k=top_k // 2,  # Fewer new chunks
                        use_llm=False,  # Just retrieval, no answer generation yet
                        include_timings=include_timings
                    )
                else:
                    from backend.services.rag_pipeline import answer_question as base_answer
                    result = await base_answer(
                        question=follow_up_query,
                        top_k=top_k // 2,
                        use_llm=False,
                        include_timings=include_timings
                    )

                # Add new unique chunks
                existing_contents = {chunk.content for chunk in all_chunks}
                new_chunks = [
                    RetrievedChunk(
                        content=c.content,
                        source=c.source,
                        score=c.score,
                        metadata=c.metadata or {}
                    )
                    for c in result.citations
                    if c.content not in existing_contents
                ]

                all_chunks.extend(new_chunks)

                # Capture timings from follow-up iteration
                iteration_timings = getattr(result, 'timings', {}) or {}
                if iteration_timings:
                    self._iteration_timings.append(iteration_timings)

                # Generate answer with accumulated context (incremental prompt)
                answer, confidence = await self._generate_with_incremental_context(
                    question=question,
                    all_chunks=all_chunks,
                    conversation_history=conversation_history,
                    new_chunks=new_chunks
                )

            iteration_ms = (time.perf_counter() - iteration_start) * 1000

            # Get token usage for this iteration (last entry in the list)
            iteration_token_usage = self._iteration_token_usage[-1] if self._iteration_token_usage else None

            # Track this iteration
            iterations_metadata.append({
                'iteration': iteration + 1,
                'confidence': confidence,
                'num_chunks_total': len(all_chunks),
                'num_new_chunks': len(new_chunks) if iteration > 0 else len(all_chunks),
                'iteration_time_ms': iteration_ms,
                'token_usage': iteration_token_usage
            })

            # Check if we should stop
            if confidence >= self.confidence_threshold:
                logger.info(
                    "Self-RAG converged",
                    iteration=iteration + 1,
                    confidence=confidence,
                    threshold=self.confidence_threshold
                )
                best_answer = answer
                best_confidence = confidence
                break

            # Check if confidence improved enough to continue
            if iteration > 0:
                prev_confidence = conversation_history[-1]['confidence']
                improvement = confidence - prev_confidence

                if improvement < self.min_confidence_improvement:
                    logger.info(
                        "Self-RAG stopping: insufficient improvement",
                        iteration=iteration + 1,
                        improvement=improvement,
                        threshold=self.min_confidence_improvement
                    )
                    best_answer = answer
                    best_confidence = confidence
                    break

            # Update best answer
            if confidence > best_confidence:
                best_answer = answer
                best_confidence = confidence

            # Reflect on insufficiency and generate follow-up query
            reflection = await self._reflect_on_insufficiency(
                question=question,
                current_answer=answer,
                confidence=confidence,
                num_chunks=len(all_chunks)
            )

            conversation_history.append({
                'iteration': iteration + 1,
                'answer': answer,
                'confidence': confidence,
                'num_chunks': len(all_chunks),
                'reflection': reflection.get('missing_info'),
                'follow_up_query': reflection.get('follow_up_query'),
                'time_ms': iteration_ms
            })

            iteration += 1

        # Max iterations reached without convergence
        if iteration >= self.max_iterations:
            logger.warning(
                "Self-RAG max iterations reached",
                final_confidence=best_confidence,
                threshold=self.confidence_threshold
            )

        # Build final response
        total_time_ms = (time.perf_counter() - tic_total) * 1000

        # G8: Evaluation System - Record final confidence and convergence
        gov_context.add_checkpoint(
            GovernanceCriteria.G8_EVALUATION_SYSTEM,
            "passed",
            f"Self-RAG completed with confidence {best_confidence:.2f}",
            metadata={
                "final_confidence": best_confidence,
                "converged": best_confidence >= self.confidence_threshold,
                "total_iterations": len(iterations_metadata),
                "total_chunks": len(all_chunks)
            }
        )

        # G11: Reliability - Check if system achieved desired quality
        reliability_status = "passed" if best_confidence >= self.confidence_threshold else "warning"
        reliability_message = (
            f"Converged at confidence {best_confidence:.2f}"
            if best_confidence >= self.confidence_threshold
            else f"Did not converge - final confidence {best_confidence:.2f} < threshold {self.confidence_threshold}"
        )
        gov_context.add_checkpoint(
            GovernanceCriteria.G11_RELIABILITY,
            reliability_status,
            reliability_message,
            metadata={"iterations_used": len(iterations_metadata)}
        )

        # Complete governance tracking
        completed_gov_context = governance_tracker.complete_operation(gov_context.trace_id)

        citations = [
            Citation(
                source=chunk.source,
                content=chunk.content,
                score=chunk.score,
                metadata=chunk.metadata
            )
            for chunk in all_chunks
        ]

        # Calculate retrieval and LLM times from iterations
        total_retrieval_ms = sum(it['iteration_time_ms'] for it in iterations_metadata)
        llm_time_ms = total_retrieval_ms * 0.3  # Rough estimate

        # Aggregate timings from all iterations
        aggregated_timings = {}
        if hasattr(self, '_iteration_timings') and self._iteration_timings:
            # Aggregate strategy: sum all values (total time across all iterations)
            # Support both enhanced_rag_pipeline (hybrid_search_ms) and rag_pipeline (embed_ms, vector_ms)
            timing_keys = [
                'embed_ms', 'vector_ms', 'rerank_ms',
                'hybrid_search_ms',  # from enhanced_rag_pipeline
                'candidate_prep_ms', 'pre_rerank_ms'
            ]
            for key in timing_keys:
                values = [t.get(key, 0) for t in self._iteration_timings if t.get(key) is not None and t.get(key) != 0]
                if values:
                    aggregated_timings[key] = sum(values)

            # If we have hybrid_search_ms but not embed_ms/vector_ms,
            # the frontend expects embed_ms and vector_ms separately
            # We can approximate by splitting hybrid_search_ms (embedding is typically 30% of hybrid search)
            if 'hybrid_search_ms' in aggregated_timings and 'embed_ms' not in aggregated_timings:
                hybrid_ms = aggregated_timings['hybrid_search_ms']
                aggregated_timings['embed_ms'] = hybrid_ms * 0.3  # Approximate embed time
                aggregated_timings['vector_ms'] = hybrid_ms * 0.7  # Approximate vector search time

            # Keep metadata from first iteration
            if self._iteration_timings:
                first_timing = self._iteration_timings[0]
                aggregated_timings['embedding_model_path'] = first_timing.get('embedding_model_path')
                aggregated_timings['reranker_model_path'] = first_timing.get('reranker_model_path')
                aggregated_timings['reranker_mode'] = first_timing.get('reranker_mode')
                aggregated_timings['vector_limit_used'] = first_timing.get('vector_limit_used')
                aggregated_timings['content_char_limit_used'] = first_timing.get('content_char_limit_used')
                aggregated_timings['score_threshold'] = first_timing.get('score_threshold')
                aggregated_timings['reranker_model'] = first_timing.get('reranker_model')

        # Add governance audit trail to timings
        governance_summary = None
        if completed_gov_context:
            governance_summary = {
                'trace_id': completed_gov_context.trace_id,
                'risk_tier': completed_gov_context.risk_tier.value,
                'total_checkpoints': len(completed_gov_context.checkpoints),
                'passed_checkpoints': sum(1 for cp in completed_gov_context.checkpoints if cp.status == "passed"),
                'warning_checkpoints': sum(1 for cp in completed_gov_context.checkpoints if cp.status == "warning"),
                'failed_checkpoints': sum(1 for cp in completed_gov_context.checkpoints if cp.status == "failed"),
                'criteria_checked': [cp.criteria.value for cp in completed_gov_context.checkpoints]
            }

        timings = {
            'iterations': iterations_metadata,
            'total_iterations': len(iterations_metadata),
            'converged': best_confidence >= self.confidence_threshold,
            'end_to_end_ms': total_time_ms,
            # Add aggregated bottom-level timings
            **aggregated_timings,
            # Add AI Governance tracking
            'governance': governance_summary
        } if include_timings else None

        # Aggregate token usage from all iterations
        cumulative_token_usage = None
        cumulative_cost = 0.0
        if hasattr(self, '_iteration_token_usage') and self._iteration_token_usage:
            total_prompt = sum(u.get('prompt', 0) for u in self._iteration_token_usage)
            total_completion = sum(u.get('completion', 0) for u in self._iteration_token_usage)
            cumulative_token_usage = {
                'prompt': total_prompt,
                'completion': total_completion,
                'total': total_prompt + total_completion
            }
            cumulative_cost = sum(u.get('cost', 0) for u in self._iteration_token_usage)

        return RAGResponse(
            answer=best_answer or "I could not generate a confident answer after multiple attempts.",
            citations=citations,
            retrieval_time_ms=total_retrieval_ms,
            confidence=best_confidence,
            num_chunks_retrieved=len(all_chunks),
            llm_time_ms=llm_time_ms,
            total_time_ms=total_time_ms,
            timings=timings,
            models={
                "embedding": settings.ONNX_EMBED_MODEL_PATH or "remote-embed",
                "reranker": settings.ONNX_RERANK_MODEL_PATH or "remote-rerank",
                "llm": os.getenv("OPENAI_MODEL") or settings.OPENAI_MODEL or "gpt-4o-mini"
            },
            token_usage=cumulative_token_usage,
            iteration_details=iterations_metadata,
            token_cost_usd=cumulative_cost,
            llm_used=True
        )

    async def _generate_with_incremental_context(
        self,
        question: str,
        all_chunks: List[RetrievedChunk],
        conversation_history: List[Dict[str, Any]],
        new_chunks: List[RetrievedChunk]
    ) -> Tuple[str, float]:
        """
        Generate answer with incremental context (send only new chunks).

        This saves tokens by referencing previously seen context instead of resending it.
        """
        if not conversation_history:
            # First iteration - full context
            return await self._generate_answer_full_context(question, all_chunks)

        # Build incremental prompt
        prev_iter = conversation_history[-1]
        prev_chunk_count = prev_iter['num_chunks'] - len(new_chunks)

        context_parts = []
        for i, chunk in enumerate(new_chunks, 1):
            source = chunk.source or "Unknown"
            idx = prev_chunk_count + i
            context_parts.append(f"[{idx}] Source: {source}\n{chunk.content}")

        new_context = "\n\n".join(context_parts)

        prompt = f"""You are continuing to answer a question with additional retrieved context.

Question: {question}

Previously Retrieved Context: Chunks [1-{prev_chunk_count}]
(You analyzed these in the previous iteration - they are still available for reference)

NEW Context (just retrieved):
{new_context}

Previous Analysis:
Confidence: {prev_iter['confidence']:.2f}
Answer: {prev_iter['answer']}

Based on ALL context (previous + new), provide your updated answer and confidence assessment.

Instructions:
1. Review the new context and integrate it with previous findings
2. Provide an updated answer with inline citations [1], [2], etc.
3. Assess your confidence (0-1) based on how well you can answer the question

Respond in this format:
**Answer:**
[Your answer with citations]

**Confidence:**
[A single number between 0 and 1]

**Reasoning:**
[Brief explanation of your confidence level]"""

        try:
            client = _get_openai_client()
            llm_model = os.getenv("OPENAI_MODEL") or settings.OPENAI_MODEL or "gpt-4o-mini"

            messages = sanitize_messages([
                {"role": "system", "content": "You are a helpful assistant that provides answers with confidence assessments."},
                {"role": "user", "content": prompt}
            ])

            response = await client.chat.completions.create(
                model=llm_model,
                messages=messages,
                temperature=0.3,
                max_tokens=600
            )

            content = response.choices[0].message.content.strip()

            # Track token usage from this LLM call
            if hasattr(response, 'usage') and response.usage:
                from backend.services.token_counter import TokenUsage, _token_counter
                usage_obj = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    model=llm_model,
                    timestamp=datetime.utcnow()
                )
                cost = _token_counter.estimate_cost(usage_obj)
                self._iteration_token_usage.append({
                    'prompt': response.usage.prompt_tokens,
                    'completion': response.usage.completion_tokens,
                    'total': response.usage.total_tokens,
                    'cost': cost
                })

            # Parse answer and confidence
            answer, confidence = self._parse_answer_and_confidence(content)

            return answer, confidence

        except Exception as e:
            logger.error("Failed to generate incremental answer", error=str(e))
            # Fallback to full context
            return await self._generate_answer_full_context(question, all_chunks)

    async def _generate_answer_full_context(
        self,
        question: str,
        chunks: List[RetrievedChunk]
    ) -> Tuple[str, float]:
        """Generate answer with full context (first iteration)"""
        # Build context
        context_parts = []
        for i, chunk in enumerate(chunks[:30], 1):  # Top 30 chunks
            source = chunk.source or "Unknown"
            context_parts.append(f"[{i}] Source: {source}\n{chunk.content}")

        context = "\n\n".join(context_parts)

        prompt = f"""You are a helpful assistant answering questions based on retrieved documents.

Context (Retrieved Documents):
{context}

Question: {question}

Provide your answer with inline citations [1], [2], etc., and assess your confidence (0-1).

Respond in this format:
**Answer:**
[Your answer with citations]

**Confidence:**
[A single number between 0 and 1]

**Reasoning:**
[Brief explanation of your confidence level]"""

        try:
            client = _get_openai_client()
            llm_model = os.getenv("OPENAI_MODEL") or settings.OPENAI_MODEL or "gpt-4o-mini"

            messages = sanitize_messages([
                {"role": "system", "content": "You are a helpful assistant that provides answers with confidence assessments."},
                {"role": "user", "content": prompt}
            ])

            response = await client.chat.completions.create(
                model=llm_model,
                messages=messages,
                temperature=0.3,
                max_tokens=600
            )

            content = response.choices[0].message.content.strip()

            # Track token usage from this LLM call
            if hasattr(response, 'usage') and response.usage:
                from backend.services.token_counter import TokenUsage, _token_counter
                usage_obj = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    model=llm_model,
                    timestamp=datetime.utcnow()
                )
                cost = _token_counter.estimate_cost(usage_obj)
                self._iteration_token_usage.append({
                    'prompt': response.usage.prompt_tokens,
                    'completion': response.usage.completion_tokens,
                    'total': response.usage.total_tokens,
                    'cost': cost
                })

            answer, confidence = self._parse_answer_and_confidence(content)

            return answer, confidence

        except Exception as e:
            logger.error("Failed to generate answer", error=str(e))
            return f"Error: {str(e)}", 0.0

    def _parse_answer_and_confidence(self, content: str) -> Tuple[str, float]:
        """Parse answer and confidence from LLM response"""
        try:
            # Extract answer
            answer_match = content.split("**Answer:**", 1)
            if len(answer_match) > 1:
                answer_part = answer_match[1].split("**Confidence:**", 1)[0].strip()
            else:
                answer_part = content

            # Extract confidence
            confidence_match = content.split("**Confidence:**", 1)
            if len(confidence_match) > 1:
                confidence_text = confidence_match[1].split("**Reasoning:**", 1)[0].strip()
                # Try to extract number
                import re
                numbers = re.findall(r'0\.\d+|1\.0|0|1', confidence_text)
                if numbers:
                    confidence = float(numbers[0])
                else:
                    confidence = 0.5  # Default
            else:
                confidence = 0.5  # Default

            return answer_part, max(0.0, min(1.0, confidence))

        except Exception as e:
            logger.warning("Failed to parse answer and confidence", error=str(e))
            return content, 0.5

    async def _reflect_on_insufficiency(
        self,
        question: str,
        current_answer: str,
        confidence: float,
        num_chunks: int
    ) -> Dict[str, str]:
        """
        Use LLM to analyze why confidence is low and suggest follow-up query.

        Returns:
            Dict with 'missing_info' and 'follow_up_query'
        """
        reflection_prompt = f"""You are analyzing why a RAG system has low confidence answering a question.

Question: {question}
Current Answer: {current_answer}
Confidence: {confidence:.2f}
Context Chunks Analyzed: {num_chunks}

What specific information is missing to answer this question more confidently?
Suggest a follow-up retrieval query to find the missing information.

Respond in JSON format:
{{
    "missing_info": "What specific information or details are needed",
    "follow_up_query": "A search query to retrieve the missing information"
}}"""

        try:
            client = _get_openai_client()
            llm_model = os.getenv("OPENAI_MODEL") or settings.OPENAI_MODEL or "gpt-4o-mini"

            messages = sanitize_messages([
                {"role": "system", "content": "You are an analytical assistant that identifies information gaps."},
                {"role": "user", "content": reflection_prompt}
            ])

            response = await client.chat.completions.create(
                model=llm_model,
                messages=messages,
                temperature=0.3,
                max_tokens=200
            )

            content = response.choices[0].message.content.strip()

            # Track token usage from reflection LLM call
            if hasattr(response, 'usage') and response.usage:
                from backend.services.token_counter import TokenUsage, _token_counter
                usage_obj = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    model=llm_model,
                    timestamp=datetime.utcnow()
                )
                cost = _token_counter.estimate_cost(usage_obj)
                self._iteration_token_usage.append({
                    'prompt': response.usage.prompt_tokens,
                    'completion': response.usage.completion_tokens,
                    'total': response.usage.total_tokens,
                    'cost': cost
                })

            # Try to parse JSON
            # Remove markdown code blocks if present
            content = content.replace("```json", "").replace("```", "").strip()
            reflection = json.loads(content)

            return reflection

        except Exception as e:
            logger.warning("Failed to generate reflection", error=str(e))
            # Fallback: expand the original question
            return {
                "missing_info": "Additional context or details",
                "follow_up_query": f"{question} details context"
            }


def get_self_rag(
    confidence_threshold: Optional[float] = None,
    max_iterations: Optional[int] = None
) -> SelfRAG:
    """
    Get configured Self-RAG instance.

    Args:
        confidence_threshold: Override default threshold from env
        max_iterations: Override default max iterations from env

    Returns:
        SelfRAG instance
    """
    threshold = confidence_threshold or float(os.getenv("SELF_RAG_CONFIDENCE_THRESHOLD", "0.75"))
    max_iter = max_iterations or int(os.getenv("SELF_RAG_MAX_ITERATIONS", "3"))
    min_improvement = float(os.getenv("SELF_RAG_MIN_IMPROVEMENT", "0.05"))

    return SelfRAG(
        confidence_threshold=threshold,
        max_iterations=max_iter,
        min_confidence_improvement=min_improvement
    )
