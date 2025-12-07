"""
Table RAG - Structured data extraction and presentation

This module provides Table RAG functionality for queries that require:
- Comparisons between multiple entities
- Lists and aggregations
- Structured data presentation

Process:
1. Hybrid retrieval (vector + BM25)
2. Entity extraction from query
3. Data structuring with LLM
4. Table generation
5. Answer synthesis with table context
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
import os
import structlog
from openai import AsyncOpenAI
from qdrant_client import QdrantClient
from backend.services.unified_llm_metrics import get_unified_metrics

logger = structlog.get_logger(__name__)

# Heuristic Excel tool keywords - expanded for better matching
_EXCEL_TOOL_KEYWORDS = [
    # Chinese keywords
    "反向用电", "抄表", "发电", "电量", "电表", "用电量", "总发电",
    # English keywords
    "kwh", "excel", "xlsx", "meter", "reading",
    "power", "generation", "energy", "consumption",
    # Month names for time-based queries
    "aug", "august", "8月", "八月"
]


def _should_use_excel_tool(question: str) -> bool:
    lowered = question.lower()
    return any(k in lowered for k in _EXCEL_TOOL_KEYWORDS)


def _analyze_excel_file(file_path: str, uploaded_file: str):
    """
    Analyze Excel file and compute total photovoltaic (PV) energy generation.

    Calculates sum of ALL photovoltaic meters' forward AND reverse energy.
    """
    try:
        import pandas as pd
    except Exception:
        return None

    p = Path(file_path)
    if not p.exists():
        return None

    try:
        df = pd.read_excel(p)
    except Exception:
        return None

    # Detect columns containing start/end readings and multiplier
    col_start = None
    col_end = None
    col_multiplier = None
    for c in df.columns:
        if "Unnamed: 4" in str(c):
            col_start = c
        if "Unnamed: 5" in str(c):
            col_end = c
        if "Unnamed: 6" in str(c):
            col_multiplier = c
    if col_start is None and len(df.columns) > 4:
        col_start = df.columns[4]
    if col_end is None and len(df.columns) > 5:
        col_end = df.columns[5]
    if col_multiplier is None and len(df.columns) > 6:
        col_multiplier = df.columns[6]
    if col_start is None or col_end is None:
        return None

    labels_col = None
    for c in df.columns:
        if "Unnamed: 3" in str(c):
            labels_col = c
            break
    if labels_col is None and len(df.columns) > 3:
        labels_col = df.columns[3]

    def _to_num(val):
        try:
            return float(val)
        except Exception:
            return None

    # Find ALL photovoltaic meter sections
    pv_meters = {}  # {meter_name: {forward_idx: int, reverse_idx: int}}
    current_meter = None

    for idx, row in df.iterrows():
        row_str = str(row.tolist())

        # Check if this row starts a new photovoltaic meter
        if '光伏电表' in row_str:
            meter_name = str(row.iloc[0]).strip()
            current_meter = meter_name
            pv_meters[current_meter] = {'forward_idx': None, 'reverse_idx': None}

        # Mark forward/reverse section starts for the current meter
        if current_meter and current_meter in pv_meters:
            if '正向用电' in row_str and pv_meters[current_meter]['forward_idx'] is None:
                pv_meters[current_meter]['forward_idx'] = idx
            elif '反向用电' in row_str and pv_meters[current_meter]['reverse_idx'] is None:
                pv_meters[current_meter]['reverse_idx'] = idx

    if not pv_meters:
        return None

    # Helper function to process a section (5 rows with energy readings)
    def process_section(start_idx: int, section_type: str):
        """Process 5 rows of energy data and return (total_delta, row_details)"""
        if start_idx is None:
            return 0.0, []

        section_df = df.iloc[start_idx: start_idx + 5]
        section_results = []
        section_total = 0.0

        for _, row in section_df.iterrows():
            label = str(row.get(labels_col, "")).strip() if labels_col else ""
            start = _to_num(row.get(col_start))
            end = _to_num(row.get(col_end))
            multiplier = _to_num(row.get(col_multiplier)) if col_multiplier else 1.0

            if start is None or end is None:
                continue

            # Apply multiplier: delta = (end - start) * multiplier
            delta_raw = end - start
            delta = delta_raw * (multiplier if multiplier else 1.0)
            section_total += delta
            section_results.append({
                "type": section_type,
                "label": label or "unknown",
                "start": start,
                "end": end,
                "multiplier": multiplier if multiplier else 1.0,
                "delta": delta,
            })

        return section_total, section_results

    # Process each photovoltaic meter's forward + reverse sections
    all_results = []
    meter_breakdown = []
    grand_total = 0.0

    for meter_name, indices in pv_meters.items():
        forward_total, forward_rows = process_section(indices['forward_idx'], "正向用电")
        reverse_total, reverse_rows = process_section(indices['reverse_idx'], "反向用电")

        meter_total = forward_total + reverse_total
        grand_total += meter_total

        all_results.extend(forward_rows)
        all_results.extend(reverse_rows)

        meter_breakdown.append({
            "meter": meter_name,
            "forward_kwh": round(forward_total, 2),
            "reverse_kwh": round(reverse_total, 2),
            "total_kwh": round(meter_total, 2),
        })

    return {
        "uploaded_file": uploaded_file,
        "file_path": str(p),
        "total_generation_kwh": round(grand_total, 2),
        "num_pv_meters": len(pv_meters),
        "meter_breakdown": meter_breakdown,
        "all_rows": all_results,
        "method": "Sum of all 光伏电表 (正向用电 + 反向用电), delta = end - start",
    }


def _resolve_excel_path(uploaded_file: str, fallback_path: Optional[str], upload_dir: Optional[str]) -> Optional[str]:
    """Resolve an Excel path from metadata, provided upload_dir, or default uploads folder."""
    # 1) Use explicit path if exists
    if fallback_path:
        p = Path(fallback_path)
        if p.exists():
            return str(p)

    # 2) Use provided upload_dir if any
    candidates = []
    if upload_dir:
        candidates.append(Path(upload_dir) / uploaded_file)

    # 3) Default uploads dir (env or data/uploads)
    default_dir = Path(os.getenv("UPLOADS_DIR", "data/uploads"))
    candidates.append(default_dir / uploaded_file)

    for cand in candidates:
        if cand.exists():
            return str(cand)

    # 4) Glob for timestamped variants
    search_dir = Path(upload_dir or default_dir)
    matches = list(search_dir.glob(f"{Path(uploaded_file).stem}*{Path(uploaded_file).suffix}"))
    if matches:
        return str(matches[-1])
    return None


class TableRAG:
    """
    Table RAG for structured data queries.

    Extracts structured information from documents and presents it in table format.
    """

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        qdrant_client: QdrantClient,
        collection_name: str = "assessment_docs_minilm",
        extraction_model: str = "gpt-4o-mini",
        generation_model: str = "gpt-4o-mini",
    ):
        self.openai_client = openai_client
        self.qdrant_client = qdrant_client
        self.collection_name = collection_name
        self.extraction_model = extraction_model
        self.generation_model = generation_model

    async def extract_query_intent(self, question: str) -> Dict[str, Any]:
        """
        Extract the user's intent from the query.
        Falls back to simple keyword extraction if LLM is unavailable.

        Returns:
            Dict with 'intent', 'extraction_time_ms', 'token_usage'
        """
        start = time.time()

        # Try LLM-based intent extraction first
        try:
            prompt = f"""Analyze this query and determine what structured data the user wants:

Query: "{question}"

Identify:
1. What entities or concepts should be extracted? (e.g., "characters", "tools", "safety measures")
2. What attributes to compare or list? (e.g., "purpose", "features", "relationships")
3. What structure? (comparison, list, aggregation)

Respond in JSON:
{{
  "query_type": "comparison|list|aggregation",
  "entities_to_extract": ["entity1", "entity2"],
  "attributes": ["attribute1", "attribute2"],
  "reasoning": "brief explanation"
}}
"""

            unified_metrics = get_unified_metrics()
            async with unified_metrics.track_llm_call(
                model=self.extraction_model,
                endpoint="table_rag_intent_extraction"
            ) as tracker:
                messages = [
                    {"role": "system", "content": "You are a query analyzer that extracts structured intent."},
                    {"role": "user", "content": prompt}
                ]
                response = await self.openai_client.chat.completions.create(
                    model=self.extraction_model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=300,
                )

                # Set context for tracking (REQUIRED for metrics to be recorded)
                tracker["messages"] = messages
                tracker["completion"] = response.choices[0].message.content

            content = response.choices[0].message.content.strip()

            # Parse JSON response
            try:
                intent = json.loads(content)
            except:
                # Fallback if JSON parsing fails
                intent = {
                    "query_type": "list",
                    "entities_to_extract": ["entities"],
                    "attributes": ["attributes"],
                    "reasoning": "Default intent"
                }

            token_usage = None
            if hasattr(response, 'usage') and response.usage:
                token_usage = {
                    'prompt': response.usage.prompt_tokens,
                    'completion': response.usage.completion_tokens,
                    'total': response.usage.total_tokens
                }

            elapsed_ms = (time.time() - start) * 1000

            return {
                'intent': intent,
                'extraction_time_ms': elapsed_ms,
                'token_usage': token_usage
            }

        except Exception as e:
            logger.warning(f"LLM intent extraction failed ({e}), falling back to keyword-based extraction")

            # FALLBACK: Simple keyword-based intent extraction
            question_lower = question.lower()

            # Detect aggregation queries (发电量, 总计, 多少, etc.)
            if any(kw in question_lower for kw in ['发电', '用电', '总', '多少', '总计', 'total', 'generation', 'sum', 'kwh']):
                query_type = "aggregation"
            # Detect comparison queries
            elif any(kw in question_lower for kw in ['比较', '对比', 'compare', 'vs', 'versus']):
                query_type = "comparison"
            else:
                query_type = "list"

            # Extract entity names (简单提取中文词汇和英文单词)
            import re
            entities = []
            # 提取中文词汇 (2-10个连续中文字符)
            chinese_entities = re.findall(r'[\u4e00-\u9fa5]{2,10}', question)
            entities.extend(chinese_entities[:3])  # 最多3个

            # 提取英文单词
            english_entities = re.findall(r'\b[a-zA-Z]{3,}\b', question)
            entities.extend(english_entities[:2])  # 最多2个

            elapsed_ms = (time.time() - start) * 1000

            return {
                'intent': {
                    "query_type": query_type,
                    "entities_to_extract": entities if entities else ["data"],
                    "attributes": ["value", "total"],
                    "reasoning": "Keyword-based extraction (LLM unavailable)"
                },
                'extraction_time_ms': elapsed_ms,
                'token_usage': None
            }

    async def hybrid_retrieve(
        self,
        question: str,
        top_k: int = 20,
        hybrid_alpha: float = 0.6
    ) -> tuple[List[Dict[str, Any]], float]:
        """
        Perform hybrid retrieval (vector + BM25).
        Falls back to direct file system search if Qdrant retrieval fails or returns no results.

        Args:
            question: User query
            top_k: Number of results to return
            hybrid_alpha: Balance between vector (1.0) and BM25 (0.0)

        Returns:
            Tuple of (chunks, retrieval_time_ms)
        """
        start = time.time()
        chunks = []

        try:
            # Use HybridRetriever class directly
            from backend.services.hybrid_retriever import HybridRetriever
            from backend.services.inference.embeddings import get_embedding

            # Get query embedding first
            query_embedding = await get_embedding(question)

            # Initialize hybrid retriever
            hybrid_retriever = HybridRetriever(
                qdrant_client=self.qdrant_client,
                collection_name=self.collection_name,
                alpha=hybrid_alpha
            )
            await hybrid_retriever.initialize()

            # Perform hybrid search
            raw_results = await hybrid_retriever.hybrid_search(
                query=question,
                query_embedding=query_embedding,
                top_k=top_k
            )

            # Convert to chunks format
            for result in raw_results:
                payload = result.get('payload', {})
                chunks.append({
                    'content': payload.get('content', ''),
                    'score': result.get('score', 0.0),
                    'metadata': {
                        'source': payload.get('source', 'unknown'),
                        'uploaded_file': payload.get('uploaded_file'),
                        **payload
                    }
                })

            retrieval_ms = (time.time() - start) * 1000

            logger.info(
                "Hybrid retrieval completed",
                num_chunks=len(chunks),
                time_ms=int(retrieval_ms)
            )

            # If we got results, return them
            if chunks:
                return chunks, retrieval_ms

            # If no results, fall through to file system search
            logger.warning("No results from Qdrant, falling back to file system search")

        except Exception as e:
            logger.warning(f"Hybrid retrieval failed ({e}), falling back to file system search")

        # FALLBACK: Search for Excel files directly in /app/data/uploads/
        import os
        import re
        from pathlib import Path

        uploads_dir = Path("/app/data/uploads")
        fallback_chunks = []

        if uploads_dir.exists():
            # Extract keywords from question
            question_lower = question.lower()
            chinese_keywords = re.findall(r'[\u4e00-\u9fa5]{2,10}', question)
            english_keywords = re.findall(r'\b[a-zA-Z]{3,}\b', question_lower)

            logger.info(f"Searching uploads directory with keywords: {chinese_keywords + english_keywords}")

            # Search for matching Excel files
            for file_path in uploads_dir.glob("*.xlsx"):
                file_name = file_path.name
                # Check if any keyword matches the filename
                matched = any(kw in file_name for kw in chinese_keywords)
                matched = matched or any(kw in file_name.lower() for kw in english_keywords)

                if matched:
                    # Create a pseudo-chunk pointing to this file
                    fallback_chunks.append({
                        'content': f"Excel file: {file_name}",
                        'score': 1.0,
                        'metadata': {
                            'uploaded_file': file_name,
                            'file_path': str(file_path),
                            'source': 'file_system_fallback'
                        }
                    })
                    logger.info(f"Found matching Excel file: {file_name}")

        retrieval_ms = (time.time() - start) * 1000

        if fallback_chunks:
            logger.info(f"File system search found {len(fallback_chunks)} matching files")
        else:
            logger.warning("No matching files found in file system search")

        return fallback_chunks, retrieval_ms

    async def structure_data(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Structure retrieved data into table format.

        Args:
            question: User query
            chunks: Retrieved document chunks
            intent: Query intent from extract_query_intent

        Returns:
            Dict with 'table_data', 'structuring_time_ms', 'token_usage'
        """
        start = time.time()

        # Prepare context from chunks
        context = "\n\n".join([
            f"[Chunk {i+1}]\n{chunk.get('content', chunk.get('payload', {}).get('content', ''))}"
            for i, chunk in enumerate(chunks[:10])
        ])

        prompt = f"""Based on the following context, structure the information as a table.

Query: {question}
Intent: {intent.get('reasoning', 'Extract structured data')}

Context:
{context}

Create a table with appropriate headers and rows. Return JSON:
{{
  "headers": ["Column1", "Column2", ...],
  "rows": [
    ["value1", "value2", ...],
    ...
  ],
  "summary": "Brief summary of the table"
}}
"""

        try:
            unified_metrics = get_unified_metrics()
            async with unified_metrics.track_llm_call(
                model=self.extraction_model,
                endpoint="table_rag_data_structuring"
            ) as tracker:
                messages = [
                    {"role": "system", "content": "You are a data structuring assistant."},
                    {"role": "user", "content": prompt}
                ]
                response = await self.openai_client.chat.completions.create(
                    model=self.extraction_model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=800,
                )

                # Set context for tracking (REQUIRED for metrics to be recorded)
                tracker["messages"] = messages
                tracker["completion"] = response.choices[0].message.content

            content = response.choices[0].message.content.strip()

            try:
                table_data = json.loads(content)
            except:
                # Fallback minimal table
                table_data = {
                    "headers": ["Information"],
                    "rows": [],
                    "summary": "Could not structure data"
                }

            token_usage = None
            if hasattr(response, 'usage') and response.usage:
                token_usage = {
                    'prompt': response.usage.prompt_tokens,
                    'completion': response.usage.completion_tokens,
                    'total': response.usage.total_tokens
                }

            elapsed_ms = (time.time() - start) * 1000

            return {
                'table_data': table_data,
                'structuring_time_ms': elapsed_ms,
                'token_usage': token_usage
            }

        except Exception as e:
            logger.error(f"Data structuring failed: {e}")
            elapsed_ms = (time.time() - start) * 1000
            return {
                'table_data': {"headers": [], "rows": [], "summary": f"Error: {str(e)}"},
                'structuring_time_ms': elapsed_ms,
                'token_usage': None
            }

    async def generate_answer(
        self,
        question: str,
        table_data: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        excel_result: Optional[Dict[str, Any]] = None,
        tool_triggered: bool = False,
        tool_execution_time_ms: float = 0.0,
        tool_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate final answer using table data and optional Excel results.

        CRITICAL: If excel_result exists, use it directly in the answer!

        Args:
            question: User query
            table_data: Structured table from structure_data
            chunks: Retrieved chunks
            excel_result: Optional Excel analysis result
            tool_triggered: Whether Excel tool was triggered
            tool_execution_time_ms: Tool execution time
            tool_error: Optional tool error message

        Returns:
            Dict with 'answer', 'generation_time_ms', 'token_usage', 'tool_usage'
        """
        start = time.time()

        # PRIORITY 1: If Excel tool succeeded, use its result directly!
        if excel_result:
            total_kwh = excel_result.get("total_generation_kwh", 0)
            num_pv_meters = excel_result.get("num_pv_meters", 0)
            meter_breakdown = excel_result.get("meter_breakdown") or []
            all_rows = excel_result.get("all_rows") or []
            file_name = excel_result.get("uploaded_file", "Excel file")

            # Build meter breakdown summary
            meter_summary = "\n".join([
                f"  - **{m.get('meter', 'Unknown')}**: "
                f"正向 {m.get('forward_kwh', 0):.2f} kWh + "
                f"反向 {m.get('reverse_kwh', 0):.2f} kWh = "
                f"**{m.get('total_kwh', 0):.2f} kWh**"
                for m in meter_breakdown
            ])

            # Build row details (show first 10 rows)
            row_details = "\n".join([
                f"  - {r.get('type', 'Unknown')} - {r.get('label', 'Unknown')}: {r.get('delta', 0):.2f} kWh"
                for r in all_rows[:10]
            ])

            answer = (
                f"根据 Excel 文件 **{file_name}** 的分析：\n\n"
                f"**总发电量**: {total_kwh:.2f} kWh\n\n"
                f"**光伏电表数量**: {num_pv_meters} 个\n\n"
                f"**各电表明细**:\n{meter_summary if meter_summary else '无电表数据'}\n\n"
                f"**计算方法**: 计算所有光伏电表的正向用电和反向用电 (本次示数 - 上次示数) 的差值总和。\n\n"
                f"**详细数据** (前10项):\n{row_details if row_details else '无明细数据'}"
            )

            elapsed_ms = (time.time() - start) * 1000

            tool_usage = {
                'triggered': tool_triggered,
                'tool_name': 'excel_analysis',
                'execution_time_ms': tool_execution_time_ms,
                'status': 'success',
                'input': {'query_keywords': _EXCEL_TOOL_KEYWORDS},
                'output': excel_result,
                'reason': tool_error
            }

            return {
                'answer': answer,
                'generation_time_ms': elapsed_ms,
                'token_usage': None,  # No LLM used, Excel provided direct answer
                'tool_usage': tool_usage
            }

        # PRIORITY 2: Use LLM with table context
        table_str = json.dumps(table_data, ensure_ascii=False, indent=2)
        context = "\n\n".join([
            f"[Source {i+1}]\n{chunk.get('content', chunk.get('payload', {}).get('content', ''))}"
            for i, chunk in enumerate(chunks[:5])
        ])

        prompt = f"""Answer the question based on the table data and context provided.

Question: {question}

Table Data:
{table_str}

Additional Context:
{context}

Provide a clear, structured answer. If the table has data, reference it in your answer.
"""

        try:
            unified_metrics = get_unified_metrics()
            async with unified_metrics.track_llm_call(
                model=self.generation_model,
                endpoint="table_rag_answer_generation"
            ) as tracker:
                messages = [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that provides clear, structured answers based on table data."
                    },
                    {"role": "user", "content": prompt}
                ]
                response = await self.openai_client.chat.completions.create(
                    model=self.generation_model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=800,
                )

                # Set context for tracking (REQUIRED for metrics to be recorded)
                tracker["messages"] = messages
                tracker["completion"] = response.choices[0].message.content

            answer = response.choices[0].message.content.strip()

            token_usage = None
            if hasattr(response, 'usage') and response.usage:
                token_usage = {
                    'prompt': response.usage.prompt_tokens,
                    'completion': response.usage.completion_tokens,
                    'total': response.usage.total_tokens
                }

            elapsed_ms = (time.time() - start) * 1000

            logger.info(
                "Answer generated",
                answer_length=len(answer),
                time_ms=int(elapsed_ms),
                tool_triggered=tool_triggered,
                tool_success=excel_result is not None
            )

            # Build tool usage metadata
            tool_usage = {
                'triggered': tool_triggered,
                'tool_name': 'excel_analysis' if tool_triggered else None,
                'execution_time_ms': tool_execution_time_ms if tool_triggered else 0,
                'status': 'success' if excel_result else ('failed' if tool_triggered else 'not_triggered'),
                'input': {
                    'query_keywords': _EXCEL_TOOL_KEYWORDS if tool_triggered else None,
                } if tool_triggered else None,
                'output': excel_result if excel_result else None,
                'reason': tool_error
            }

            return {
                'answer': answer,
                'generation_time_ms': elapsed_ms,
                'token_usage': token_usage,
                'tool_usage': tool_usage
            }

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            elapsed_ms = (time.time() - start) * 1000
            return {
                'answer': f"Error generating answer: {str(e)}",
                'generation_time_ms': elapsed_ms,
                'token_usage': None,
                'tool_usage': {
                    'triggered': False,
                    'tool_name': None,
                    'execution_time_ms': 0,
                    'status': 'not_triggered',
                    'input': None,
                    'output': None,
                    'reason': str(e)
                }
            }

    def _format_table_markdown(self, headers: List[str], rows: List[List[str]]) -> str:
        """Format table data as markdown table."""
        if not headers or not rows:
            return "No table data available"

        # Header row
        table = "| " + " | ".join(headers) + " |\n"

        # Separator row
        table += "| " + " | ".join(["---"] * len(headers)) + " |\n"

        # Data rows
        for row in rows:
            # Ensure row has same length as headers
            padded_row = (row + [""] * len(headers))[:len(headers)]
            table += "| " + " | ".join(str(cell) for cell in padded_row) + " |\n"

        return table

    async def answer_question(
        self,
        question: str,
        top_k: int = 20,
        hybrid_alpha: float = 0.6
    ) -> Dict[str, Any]:
        """
        Main entry point for Table RAG.

        Args:
            question: User query
            top_k: Number of chunks to retrieve
            hybrid_alpha: Hybrid search balance

        Returns:
            Complete response with answer, table_data, timings, token_usage
        """
        total_start = time.time()

        # Step 1: Extract query intent
        intent_result = await self.extract_query_intent(question)
        intent = intent_result['intent']

        # Step 2: Hybrid retrieval
        chunks, retrieval_ms = await self.hybrid_retrieve(question, top_k, hybrid_alpha)

        # Step 3: Structure data
        structure_result = await self.structure_data(question, chunks, intent)
        table_data = structure_result['table_data']
        structured_rows = table_data.get('rows', [])

        # Step 4: Optional Excel tool (only if question or context suggests meter spreadsheets)
        tool_triggered = False
        tool_error = None
        excel_result = None
        tool_exec_ms = 0.0
        try:
            # Trigger if query mentions metering / power terms OR retrieved chunks have an Excel path
            has_excel_meta = any(
                (c.get('metadata') or {}).get('file_path') or (c.get('metadata') or {}).get('uploaded_file')
                for c in chunks
            )
            if _should_use_excel_tool(question) or has_excel_meta:
                tool_triggered = True
                tool_start = time.time()
                excel_chunks = [
                    c for c in chunks
                    if (c.get('metadata') or {}).get('file_path') or (c.get('metadata') or {}).get('uploaded_file')
                ]
                for ch in excel_chunks:
                    meta = ch.get('metadata') or {}
                    uploaded_file = meta.get('uploaded_file') or meta.get('file_name') or meta.get('file')
                    upload_dir = meta.get('upload_dir')
                    fallback_path = meta.get('file_path')
                    resolved = None
                    if uploaded_file:
                        resolved = _resolve_excel_path(uploaded_file, fallback_path, upload_dir)
                    elif fallback_path:
                        resolved = _resolve_excel_path(Path(fallback_path).name, fallback_path, upload_dir)
                    if not resolved:
                        continue
                    excel_result = _analyze_excel_file(resolved, uploaded_file or Path(resolved).name)
                    if excel_result:
                        logger.info(
                            "✅ Excel tool SUCCESS",
                            file=excel_result.get('uploaded_file'),
                            total_kwh=excel_result.get('total_generation_kwh', 0),
                            num_pv_meters=excel_result.get('num_pv_meters', 0)
                        )
                        break
                if not excel_result:
                    tool_error = "No Excel file found in retrieved context or failed to parse."
                tool_exec_ms = (time.time() - tool_start) * 1000
        except Exception as e:
            import traceback
            tool_error = str(e)
            tool_exec_ms = (time.time() - total_start) * 1000
            logger.error("Excel tool execution failed", error=str(e), traceback=traceback.format_exc())

        # Step 5: Generate answer
        answer_result = await self.generate_answer(
            question,
            table_data,
            chunks,
            excel_result=excel_result,
            tool_triggered=tool_triggered,
            tool_execution_time_ms=tool_exec_ms,
            tool_error=tool_error,
        )

        # Aggregate timings
        total_ms = (time.time() - total_start) * 1000

        timings = {
            'total_ms': total_ms,
            'intent_extraction_ms': intent_result['extraction_time_ms'],
            'structuring_ms': structure_result['structuring_time_ms'],
            'answer_generation_ms': answer_result['generation_time_ms'],
            'retrieval_ms': retrieval_ms,
            'embed_ms': retrieval_ms * 0.3,  # Estimate: ~30% of retrieval time for embedding
            'vector_ms': retrieval_ms * 0.4,  # Estimate: ~40% for vector search
            'candidate_prep_ms': retrieval_ms * 0.1,  # Estimate: ~10% for candidate prep
            'rerank_ms': retrieval_ms * 0.2,  # Estimate: ~20% for reranking (BM25 fusion)
        }

        # Extract tool usage metadata (do not assume local variables exist in this scope)
        tool_usage = answer_result.get('tool_usage')
        if not tool_usage:
            status = 'success' if excel_result else ('failed' if tool_triggered else 'not_triggered')
            tool_usage = {
                'triggered': tool_triggered,
                'tool_name': 'excel_analysis' if tool_triggered else None,
                'execution_time_ms': tool_exec_ms if tool_triggered else 0,
                'status': status,
                'reason': tool_error,
                'input': {'query_keywords': _EXCEL_TOOL_KEYWORDS} if tool_triggered else None,
                'output': excel_result
            }

        # Aggregate token usage (flatten for UI)
        token_usage_breakdown = {
            'intent_extraction': intent_result.get('token_usage'),
            'data_structuring': structure_result.get('token_usage'),
            'answer_generation': answer_result.get('token_usage'),
        }
        prompt_tokens = sum((u.get('prompt', 0) for u in token_usage_breakdown.values() if u), 0)
        completion_tokens = sum((u.get('completion', 0) for u in token_usage_breakdown.values() if u), 0)
        total_tokens = prompt_tokens + completion_tokens

        # If structuring failed (no rows) but excel tool produced output, inject a minimal table
        if (not structured_rows) and tool_usage.get('output'):
            excel_out = tool_usage['output']
            # Use new field name: total_generation_kwh instead of reverse_energy_kwh
            total_val = excel_out.get('total_generation_kwh', excel_out.get('reverse_energy_kwh', 0))
            all_rows = excel_out.get('all_rows') or excel_out.get('rows') or []
            table_data = {
                'headers': ['类型', '标签', '上次', '本次', '倍率', '差值 (kWh)'],
                'rows': [
                    [r.get('type', ''), r.get('label', ''), r.get('start', 0), r.get('end', 0), r.get('multiplier', 1), r.get('delta', 0)]
                    for r in all_rows
                ],
                'summary': f"Excel 分析: 总发电量 {total_val:.2f} kWh"
            }
            structured_rows = table_data['rows']

        # Get actual model paths from environment
        import os
        embed_model = os.getenv('ONNX_EMBED_MODEL_PATH', './models/bge-m3-embed-int8')
        rerank_model = os.getenv('ONNX_RERANK_MODEL_PATH', './models/bge-reranker-int8')

        # Calculate token cost (gpt-4o-mini pricing)
        # Input: $0.150 / 1M tokens, Output: $0.600 / 1M tokens
        token_cost_usd = (prompt_tokens * 0.150 + completion_tokens * 0.600) / 1_000_000

        result = {
            'answer': answer_result['answer'],
            'table_data': table_data,
            'query_intent': intent,
            'num_chunks_retrieved': len(chunks),
            'timings': timings,
            'token_usage': {
                'prompt': prompt_tokens,
                'completion': completion_tokens,
                'total': total_tokens
            },
            'total_tokens': total_tokens,
            'token_cost_usd': token_cost_usd,  # Add token cost
            'tool_usage': tool_usage,  # Add tool usage to response
            'excel_result': tool_usage.get('output'),  # Surface excel analysis for UI
            'models': {
                'embedding': embed_model,
                'reranker': rerank_model,
                'llm': self.generation_model,
            },
        }

        logger.info(
            "Table RAG completed",
            total_ms=int(total_ms),
            num_rows=len(table_data.get('rows', [])),
            total_tokens=total_tokens,
            tool_triggered=tool_usage.get('triggered', False),
            tool_status=tool_usage.get('status', 'not_triggered')
        )

        return result
