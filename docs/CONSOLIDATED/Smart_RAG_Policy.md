# Smart RAG Strategy Policy (Online / Unsupervised)

Current behavior: simple query classification → Hybrid; complex → Iterative; graph-type → Graph RAG; otherwise Table/Specialized branches. To improve accuracy, use an online bandit-style policy with unsupervised rewards.

## Candidate Strategies (arms)
- `hybrid` (BM25+vector)
- `iterative` (self-RAG)
- Graph/Table are gated by explicit intent (not bandit arms).
- Multi-collection is a scope flag, not a bandit arm; if desired, you could split arms into “hybrid-single” vs “hybrid-multi”.

## Context Features (for policy input)
- Query length, entity count, question type (classification signal)
- Retrieval density: BM25 hit count, vector scores, overlap
- Rerank margin: score(top1) - score(top2)
- Cache signals: answer cache hit? strategy cache hit?
- Collection coverage: user/system scope, file_path presence
- Cost/latency budget: recent P95 for each arm

## Unsupervised Reward (no labels)
- Relevance proxy: rerank margin (higher is better), retrieval diversity
- Consistency proxy: self-consistency or second-pass rerank agreement (optional)
- Latency penalty: -λ * (latency_ms / budget_ms)
- Cache bonus: +δ if answer cache hit
- Confidence proxy: LLM logprobs if available, or shorter/concise answer heuristic
- Optional human signal: thumbs-up/down if UI supports

## Policy (online)
- Use Thompson Sampling or UCB per arm with priors initialized from historical runs.
- Update after each request:
  - reward = w1*margin + w2*diversity - w3*latency + w4*cache_bonus + w5*consistency
  - normalize to [0,1]; clamp
  - update Beta/Normal-Inverse-Gamma (per chosen bandit variant)
- Safety guard:
  - If classifier/heuristics indicate graph/table intent → include those arms in the bandit choice (not just hybrid/iterative).
  - Otherwise sample from bandit over available arms, respecting latency budget.

## Logging & Telemetry
- Log chosen arm, context features, reward components, and final reward.
- Expose metrics: per-arm win-rate, average latency, average reward; export to Prometheus.

## Integration Steps
1) Add a lightweight policy module (bandit) with in-memory state; persist to disk/cache optionally.
2) In `ask-smart` flow: build context features, filter allowed arms, let policy pick; store choice in response.
3) After answer: compute unsupervised reward, update bandit state.
4) Surface choice/reason in UI (“Selected: Iterative | Reason: high complexity, high margin history”).
5) Add config toggles in `.env` for enabling bandit, weights (w1..w5), latency budget, and exploration rate.

## Defaults (suggested)
- Arms: hybrid, iterative; add graph/table when intent/heuristic flags them.
- Bandit: Thompson Sampling (Beta-Bernoulli on reward>threshold)
- Reward threshold: 0.5 after normalization
- Weights: margin 0.4, latency 0.2, diversity 0.1, cache 0.1, consistency 0.2
- Latency budget: 8s; λ tuned so over-budget heavily penalizes
