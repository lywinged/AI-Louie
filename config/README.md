# Smart RAG Configuration

## 📁 Bandit State Files

### default_bandit_state.json
Pre-warmed Thompson Sampling bandit weights for Smart RAG strategy selection.

**Current Performance (as of last update):**
- **Graph RAG**: 69.6% success rate (62 trials)
- **Iterative RAG**: 56.5% success rate (15 trials)
- **Table RAG**: 47.6% success rate (25 trials)
- **Hybrid RAG**: 42.3% success rate (67 trials)

Total trials: **169**

### Loading Priority

The system loads bandit state in this order:

1. **Runtime state**: `/app/cache/smart_bandit_state.json` (persisted across container restarts)
2. **Default config**: `/app/config/default_bandit_state.json` (this file - used on first run)
3. **Cold start**: Uniform priors (alpha=1, beta=1 for all strategies)

### Usage

**No warm-up needed!** The system will:
- ✅ Automatically load the pre-warmed weights on startup
- ✅ Continue learning and updating weights in `/app/cache/smart_bandit_state.json`
- ✅ Persist state across container restarts via Docker volume mount

### Updating Default Weights

To update the default weights after accumulating more trials:

```bash
# Copy current runtime state to default config
cp cache/smart_bandit_state.json config/default_bandit_state.json
```

### Manual Warm-Up (Optional)

Only needed if you want to reset and re-train:

```bash
# Run warm-up script (will create new weights in cache/)
python scripts/warm_smart_bandit.py --rounds 5

# Copy to default config
cp cache/smart_bandit_state.json config/default_bandit_state.json
```

## 🔧 Environment Variables

Configure in `.env`:

```bash
# Bandit state file path (inside container)
BANDIT_STATE_FILE=/app/cache/smart_bandit_state.json

# Enable/disable Thompson Sampling bandit
SMART_RAG_BANDIT_ENABLED=true
```

## 📊 Monitoring

View strategy selection in real-time:
- Grafana Dashboard: http://localhost:3000/d/ai-governance-dashboard
- Prometheus Metrics: http://localhost:8888/metrics
