# UI & Visualization Appendix

Consolidates: `RAG_UI_DEMO_GUIDE.md`, `RAG_VISUALIZATION_SUMMARY.md`.

## Strategy & Steps
- Show chosen strategy (with multi-collection label), reason, step list (Query Classification/Cache/Embed/Hybrid/Rerank/LLM).
- Timing breakdown: embed/vector/rerank/LLM/total; model names.

## Graph RAG
- Plotly + NetworkX, nodes colored by type; query entities displayed even with no edges.
- Expandable relationship list; export JSON/CSV supported.

## Table RAG
- Shows Excel tool status/time/output, total kWh and breakdown; if no table structure, fills with tool output.

## Tokens/Cost
- Displays token usage and estimated cost; cache hits show 0 tokens.
