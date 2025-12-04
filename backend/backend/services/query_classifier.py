"""
Query difficulty classifier for adaptive model selection.

Classifies queries into difficulty levels to determine optimal embedding/reranking models.
"""
import re
from enum import Enum
from typing import Dict, Tuple
import structlog

logger = structlog.get_logger(__name__)


class QueryDifficulty(str, Enum):
    """Query difficulty levels"""
    SIMPLE = "simple"      # Simple factual questions - use fast MiniLM
    MODERATE = "moderate"  # Multi-concept or context-dependent - use BGE if available
    COMPLEX = "complex"    # Deep reasoning, relationships, comparison - always use BGE


class QueryClassifier:
    """
    Classifies query difficulty to determine optimal model selection.

    Strategy:
    - SIMPLE: Short factual queries, single concept → MiniLM (fast)
    - MODERATE: Multi-concept, medium length → BGE preferred
    - COMPLEX: Relationships, comparisons, deep reasoning → BGE required
    """

    def __init__(self):
        # Complex query indicators
        self.complex_patterns = [
            # Relationship queries (Graph RAG indicators)
            r'\b(relationship|relate|connection|link|associate|interact)\b',
            r'\b(between|among|versus|vs|compared to|difference)\b',
            r'\b(how does .+ affect|impact of|influence on)\b',

            # Comparative/analytical queries
            r'\b(compare|contrast|analyze|evaluate|assess)\b',
            r'\b(similarities|differences|advantages|disadvantages)\b',
            r'\b(pros and cons|trade-?offs?)\b',

            # Multi-entity queries
            r'\b(all|every|each|multiple|various|different)\b.*\b(characters?|entities|items|elements)\b',

            # Deep reasoning
            r'\b(explain why|reasoning|rationale|implications)\b',
            r'\b(in-?depth|detailed|comprehensive|thorough)\b',
            r'\b(step-?by-?step|process|methodology)\b',

            # Chinese complex patterns
            r'(关系|联系|区别|对比|影响)',
            r'(详细|深入|全面|完整)',
            r'(所有|每个|各个).*?(人物|角色|实体)',
            r'(为什么|怎么样|如何)',
        ]

        # Moderate complexity indicators
        self.moderate_patterns = [
            # Multiple concepts
            r'\b(and|or|also|additionally|furthermore)\b',
            r'\b(various|several|multiple)\b',
            r'\b(including|such as|for example)\b',

            # Context-dependent
            r'\b(when|where|how|under what)\b',
            r'\b(context|situation|scenario|case)\b',

            # Chinese moderate patterns
            r'(以及|或者|还有)',
            r'(哪些|什么时候|怎么)',
        ]

        # Simple query indicators (single concept, factual)
        self.simple_patterns = [
            # Basic factual
            r'^\s*what is\s+\w+\??$',
            r'^\s*who is\s+\w+\??$',
            r'^\s*define\s+\w+\??$',

            # Chinese simple patterns
            r'^\s*什么是.{1,10}\??$',
            r'^\s*谁是.{1,10}\??$',
        ]

        # Compile all patterns
        self.complex_regex = re.compile('|'.join(self.complex_patterns), re.IGNORECASE)
        self.moderate_regex = re.compile('|'.join(self.moderate_patterns), re.IGNORECASE)
        self.simple_regex = re.compile('|'.join(self.simple_patterns), re.IGNORECASE)

    def classify_query(self, question: str) -> Tuple[QueryDifficulty, str]:
        """
        Classify query difficulty.

        Args:
            question: User's question

        Returns:
            Tuple of (difficulty_level, reason)
        """
        # Strip whitespace
        q = question.strip()

        # Check for complex patterns first (highest priority)
        if self.complex_regex.search(q):
            reason = "Complex: Relationships/comparisons/deep reasoning detected"
            logger.info("Query classified as COMPLEX", question=q[:50], reason=reason)
            return QueryDifficulty.COMPLEX, reason

        # Check for moderate patterns
        if self.moderate_regex.search(q):
            reason = "Moderate: Multiple concepts or context-dependent"
            logger.info("Query classified as MODERATE", question=q[:50], reason=reason)
            return QueryDifficulty.MODERATE, reason

        # Check for simple patterns
        if self.simple_regex.search(q):
            reason = "Simple: Basic factual question"
            logger.info("Query classified as SIMPLE", question=q[:50], reason=reason)
            return QueryDifficulty.SIMPLE, reason

        # Length-based heuristic as fallback
        word_count = len(q.split())

        if word_count <= 5:
            reason = f"Simple: Short query ({word_count} words)"
            logger.info("Query classified as SIMPLE", question=q[:50], reason=reason)
            return QueryDifficulty.SIMPLE, reason
        elif word_count <= 15:
            reason = f"Moderate: Medium-length query ({word_count} words)"
            logger.info("Query classified as MODERATE", question=q[:50], reason=reason)
            return QueryDifficulty.MODERATE, reason
        else:
            reason = f"Complex: Long query ({word_count} words)"
            logger.info("Query classified as COMPLEX", question=q[:50], reason=reason)
            return QueryDifficulty.COMPLEX, reason

    def get_recommended_models(
        self,
        difficulty: QueryDifficulty,
        bge_available: bool = True
    ) -> Dict[str, str]:
        """
        Get recommended models based on difficulty.

        Args:
            difficulty: Query difficulty level
            bge_available: Whether BGE models are available

        Returns:
            Dict with 'embedding' and 'reranker' model paths
        """
        if difficulty == QueryDifficulty.SIMPLE:
            # Always use fast MiniLM for simple queries
            return {
                'embedding': './models/minilm-embed-int8',
                'reranker': './models/minilm-reranker-onnx',
                'reason': 'Simple query → Fast MiniLM models'
            }

        elif difficulty == QueryDifficulty.MODERATE:
            # Use BGE if available, otherwise MiniLM
            if bge_available:
                return {
                    'embedding': './models/bge-m3-embed-int8',
                    'reranker': './models/bge-reranker-int8',
                    'reason': 'Moderate query → BGE models (better accuracy)'
                }
            else:
                return {
                    'embedding': './models/minilm-embed-int8',
                    'reranker': './models/minilm-reranker-onnx',
                    'reason': 'Moderate query → MiniLM (BGE not available)'
                }

        else:  # COMPLEX
            # Always prefer BGE for complex queries
            if bge_available:
                return {
                    'embedding': './models/bge-m3-embed-int8',
                    'reranker': './models/bge-reranker-int8',
                    'reason': 'Complex query → BGE models (required for accuracy)'
                }
            else:
                # Warn if BGE not available for complex query
                logger.warning(
                    "Complex query but BGE not available, falling back to MiniLM",
                    question=difficulty
                )
                return {
                    'embedding': './models/minilm-embed-int8',
                    'reranker': './models/minilm-reranker-onnx',
                    'reason': 'Complex query → MiniLM fallback (BGE not available - accuracy may suffer)'
                }


    async def get_strategy(
        self,
        question: str,
        use_llm: bool = True,
        use_cache: bool = True
    ) -> Dict[str, any]:
        """
        Get optimal RAG strategy for the given question.

        Returns a strategy dict with:
        - query_type: str (classification type)
        - description: str (explanation)
        - use_graph_rag: bool (whether to use Graph RAG)
        - use_table_rag: bool (whether to use Table RAG)
        - top_k: int (recommended number of results)
        - hybrid_alpha: float (vector vs BM25 weight)
        - classification_tokens: dict | None (LLM token usage)
        - classification_source: str (llm|keyword|cache)
        """
        import time
        from backend.services.rag_pipeline import _get_openai_client
        import os
        import json

        q_lower = question.lower()

        # === Priority 1: Table RAG (结构化数据/列表/比较/Excel) ===
        table_keywords = [
            # 中文关键词
            r'(列出|列举|有哪些|所有|比较|对比|区别|异同|优缺点|差异)',
            r'(表格|数据|统计|反向用电|发电|用电|抄表|电表|excel|kwh|倍率)',
            r'(列表|清单|目录|分类|汇总|总计|合计)',
            # 英文关键词
            r'\b(list|compare|contrast|difference|similarity|versus|vs)\b',
            r'\b(table|data|statistics|excel|spreadsheet|aggregate|sum)\b',
            r'\b(all|every|each)\s+(tools?|items?|elements?|features?)\b',
        ]

        import re
        table_regex = re.compile('|'.join(table_keywords), re.IGNORECASE)

        if table_regex.search(question):
            logger.info(f"✅ Table RAG selected (keyword match)", query=q_lower[:50])
            return {
                'query_type': 'structured_data',
                'description': 'Structured data query requiring table presentation',
                'use_graph_rag': False,
                'use_table_rag': True,
                'top_k': 20,  # Higher for aggregation
                'hybrid_alpha': 0.6,
                'classification_tokens': None,
                'classification_source': 'keyword'
            }

        # === Priority 2: Graph RAG (关系查询) ===
        graph_keywords = [
            # 关系关键词 (中文)
            r'(关系|联系|连接|相关|交互|影响|作用)',
            r'(人物|角色|角色关系|人物关系)',
            r'(之间|与.*之间|和.*的关系)',
            r'(如何影响|如何作用|如何关联)',
            # 关系关键词 (英文)
            r'\b(relationship|relation|connection|link|associate|interact)\b',
            r'\b(between|among|with)\b.*\b(and|or)\b',
            r'\b(how does .+ affect|impact of|influence on)\b',
            r'\b(character|person|entity|agent)\s+(relationship|interaction)\b',
            r'\b(all|every)\s+(relationship|connection)\b',
        ]

        graph_regex = re.compile('|'.join(graph_keywords), re.IGNORECASE)

        if graph_regex.search(question):
            logger.info(f"✅ Graph RAG selected (relationship query)", query=q_lower[:50])
            return {
                'query_type': 'relationship_query',
                'description': 'Relationship query requiring graph traversal',
                'use_graph_rag': True,
                'use_table_rag': False,
                'top_k': 15,
                'hybrid_alpha': 0.7,
                'classification_tokens': None,
                'classification_source': 'keyword'
            }

        # === Priority 3: Iterative RAG (复杂查询) ===
        complex_keywords = [
            # 深度分析关键词 (中文)
            r'(分析|解释|说明|阐述|讨论)',
            r'(详细|深入|全面|完整|综合)',
            r'(为什么|怎么样|如何|原理|机制)',
            r'(步骤|流程|过程|方法|方式)',
            # 深度分析关键词 (英文)
            r'\b(explain|analyze|describe|discuss|elaborate)\b',
            r'\b(detailed|in-depth|comprehensive|thorough|complete)\b',
            r'\b(why|how|what are the steps|process|methodology)\b',
            r'\b(pros and cons|advantages|disadvantages|trade-?offs?)\b',
        ]

        complex_regex = re.compile('|'.join(complex_keywords), re.IGNORECASE)

        # 长度判断: 16+ words = complex
        word_count = len(question.split())

        if complex_regex.search(question) or word_count >= 16:
            logger.info(f"✅ Iterative RAG selected (complex query)", query=q_lower[:50])
            return {
                'query_type': 'complex_analysis',
                'description': 'Complex query requiring iterative refinement',
                'use_graph_rag': False,
                'use_table_rag': False,
                'top_k': 10,
                'hybrid_alpha': 0.7,
                'classification_tokens': None,
                'classification_source': 'keyword'
            }

        # === Priority 4: Hybrid RAG (简单查询) ===
        # Default to hybrid search for simple factual queries
        logger.info(f"✅ Hybrid RAG selected (simple query)", query=q_lower[:50])
        return {
            'query_type': 'factual_detail',
            'description': 'Simple factual query using hybrid search',
            'use_graph_rag': False,
            'use_table_rag': False,
            'top_k': 5,
            'hybrid_alpha': 0.7,
            'classification_tokens': None,
            'classification_source': 'keyword'
        }


# Global classifier instance
_query_classifier = None


def get_query_classifier() -> QueryClassifier:
    """Get or create global query classifier."""
    global _query_classifier
    if _query_classifier is None:
        _query_classifier = QueryClassifier()
    return _query_classifier
