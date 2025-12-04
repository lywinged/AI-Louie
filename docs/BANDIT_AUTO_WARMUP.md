# Bandit Auto-Loading - Pre-warmed Weights

**Created:** 2025-12-04
**Status:** ✅ Implemented

---

## 🎯 Overview

The Smart RAG bandit now automatically loads pre-warmed weights on startup, eliminating the need for manual warm-up on every deployment.

### Problem Solved

Previously, after every backend restart:
- Bandit started with cold uniform priors (α=1.0, β=1.0 for all strategies)
- Required 5-10 minutes of warm-up queries to learn strategy performance
- Poor strategy selection until sufficient data collected
- Example: Table RAG being selected for simple author queries

### Solution

**Three-tier loading strategy:**

1. **Runtime state** (`cache/smart_bandit_state.json`)
   - Updated continuously during operation
   - Preserves learned weights across restarts
   - Location: `/tmp/smart_bandit_state.json` (Docker) or `./cache/` (local)

2. **Default pre-warmed state** (`config/default_bandit_state.json`)
   - Pre-warmed weights from comprehensive testing
   - Committed to git repository
   - Used when runtime state doesn't exist

3. **Cold start fallback** (uniform priors)
   - Only used if both above files missing
   - Logs warning to run warm-up script

---

## 📁 File Structure

```
AI-Louie/
├── cache/
│   └── smart_bandit_state.json      # Runtime state (auto-updated)
├── config/
│   └── default_bandit_state.json    # Pre-warmed defaults (git-tracked)
└── scripts/
    ├── warm_smart_bandit.py         # Warm-up script
    └── save_warmed_bandit.py        # Save current state as default
```

---

## 🚀 Usage

### For Developers: One-Time Setup

After making changes to RAG strategies or want to update default weights:

```bash
# 1. Run comprehensive warm-up
python scripts/warm_smart_bandit.py --rounds 3

# 2. Save warmed state as default
python scripts/save_warmed_bandit.py

# 3. Commit to git
git add config/default_bandit_state.json
git commit -m "Update default bandit weights"
```

### For Deployment: Automatic

**No manual steps needed!** The backend automatically:

1. Checks for runtime state → Load if exists
2. Falls back to default config → Load pre-warmed weights
3. Falls back to cold start → Log warning

```
Backend startup log:
2025-12-04 05:10:00 [info] Loaded default pre-warmed bandit state from ./config/default_bandit_state.json
```

---

## 📊 Default Weights Example

```json
{
  "hybrid": {
    "alpha": 6.30,
    "beta": 5.70
  },
  "iterative": {
    "alpha": 3.50,
    "beta": 2.80
  },
  "graph": {
    "alpha": 14.45,
    "beta": 6.55
  },
  "table": {
    "alpha": 8.42,
    "beta": 8.58
  }
}
```

**Interpretation:**
- **Hybrid RAG**: Mean = 0.525, good for quick factual queries
- **Iterative Self-RAG**: Mean = 0.556, better for complex reasoning
- **Graph RAG**: Mean = 0.688, **best** for relationship analysis
- **Table RAG**: Mean = 0.495, good for structured data

---

## 🔄 Update Workflow

### When to Update Default Weights

- After adding new RAG strategies
- After improving existing strategies
- After dataset changes
- Quarterly maintenance (recommended)

### How to Update

```bash
# Clear existing runtime state to force fresh learning
rm cache/smart_bandit_state.json

# Run warm-up with comprehensive queries
python scripts/warm_smart_bandit.py --rounds 5

# Verify weights look reasonable
cat cache/smart_bandit_state.json

# Save as new default
python scripts/save_warmed_bandit.py

# Commit
git add config/default_bandit_state.json
git commit -m "Update bandit weights after [reason]"
```

---

## 🧪 Testing

### Test Auto-Loading

```bash
# 1. Clear runtime state
rm cache/smart_bandit_state.json
docker-compose restart backend

# 2. Check logs
docker logs backend-api --tail 50 | grep "bandit state"

# Expected output:
# "Loaded default pre-warmed bandit state from ./config/default_bandit_state.json"

# 3. Test query
curl -X POST http://localhost:8888/api/rag/ask-smart \
  -H "Content-Type: application/json" \
  -d '{"question":"Who wrote Pride and Prejudice?","top_k":3}' \
  | jq '.selected_strategy'

# Should select Hybrid RAG (not Table RAG)
```

### Verify Weights Persist

```bash
# 1. Submit feedback to update weights
curl -X POST http://localhost:8888/api/rag/feedback \
  -d '{"query_id":"...","rating":1.0}'

# 2. Restart backend
docker-compose restart backend

# 3. Check runtime state was loaded
docker logs backend-api | grep "Loaded bandit state from"

# Expected: Loads from /tmp/smart_bandit_state.json
```

---

## 🔧 Configuration

### Environment Variables

```bash
# Override bandit state file location
export BANDIT_STATE_FILE="/custom/path/bandit_state.json"
```

### Docker Volume Mapping

In `docker-compose.yml`:

```yaml
services:
  backend:
    volumes:
      - ./cache:/tmp  # Maps cache/ to /tmp inside container
      - ./config:/app/config:ro  # Read-only default config
```

---

## 📈 Benefits

### Before (Manual Warm-up)

```
Time 0:00 → Deploy backend
Time 0:01 → First query: Table RAG (wrong choice)
Time 0:02 → Second query: Table RAG (still wrong)
Time 5:00 → Run manual warm-up script
Time 10:00 → Warm-up complete, good strategy selection
```

### After (Auto-Loading)

```
Time 0:00 → Deploy backend
Time 0:01 → Loads config/default_bandit_state.json
Time 0:02 → First query: Hybrid RAG ✅ (correct choice)
Time 0:03 → Second query: Graph RAG ✅ (correct choice)
```

**Result:** Immediate good performance, no warm-up delay

---

## ⚠️ Notes

### Git Tracking

- ✅ **DO commit:** `config/default_bandit_state.json`
- ❌ **DO NOT commit:** `cache/smart_bandit_state.json` (runtime state)

### Cache vs Config

| File | Purpose | Frequency | Git |
|------|---------|-----------|-----|
| `cache/smart_bandit_state.json` | Runtime state | Updated every query | ❌ No |
| `config/default_bandit_state.json` | Default config | Updated quarterly | ✅ Yes |

### Backward Compatibility

If `config/default_bandit_state.json` is missing:
- Backend falls back to cold start (uniform priors)
- Logs warning message
- Still functional, just needs warm-up

---

## 🎓 Best Practices

1. **Regular Updates**
   - Update default weights every 3 months
   - After major strategy changes

2. **Version Control**
   - Tag releases with bandit weights version
   - Example: `v1.2.0-bandit-warmed`

3. **Documentation**
   - Document what queries were used for warm-up
   - Track performance metrics before/after

4. **Testing**
   - Always test strategy selection after updating weights
   - Run evaluation suite with new defaults

---

## 📚 Related Docs

- [SMART_RAG_BANDIT_LEARNING.md](./SMART_RAG_BANDIT_LEARNING.md) - Bandit algorithm details
- [BANDIT_PERSISTENCE_GUIDE.md](./BANDIT_PERSISTENCE_GUIDE.md) - Persistence mechanism
- [USER_FEEDBACK_MECHANISM.md](./USER_FEEDBACK_MECHANISM.md) - How feedback updates weights

---

**Version:** 1.0
**Last Updated:** 2025-12-04
**Maintainer:** AI Team
