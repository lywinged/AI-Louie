#!/usr/bin/env python3
"""
Save current warmed bandit state as default configuration

This script copies the current bandit state to the config directory
so it can be used as the default state for fresh deployments.
"""
import json
import shutil
from pathlib import Path

# Paths
CACHE_STATE = Path("cache/smart_bandit_state.json")
DEFAULT_STATE = Path("config/default_bandit_state.json")

def main():
    """Save current bandit state as default"""
    if not CACHE_STATE.exists():
        print(f"❌ Error: {CACHE_STATE} does not exist")
        print("   Please run warm_smart_bandit.py first to generate the state")
        return 1

    # Read current state
    with open(CACHE_STATE, 'r') as f:
        state = json.load(f)

    # Validate state has all required strategies
    required_strategies = ['hybrid', 'iterative', 'graph', 'table']
    for strategy in required_strategies:
        if strategy not in state:
            print(f"❌ Error: Missing strategy '{strategy}' in bandit state")
            return 1
        if 'alpha' not in state[strategy] or 'beta' not in state[strategy]:
            print(f"❌ Error: Strategy '{strategy}' missing alpha/beta values")
            return 1

    # Create config directory if it doesn't exist
    DEFAULT_STATE.parent.mkdir(parents=True, exist_ok=True)

    # Save as default
    shutil.copy(CACHE_STATE, DEFAULT_STATE)

    print(f"✅ Saved warmed bandit state to {DEFAULT_STATE}")
    print(f"\nCurrent bandit weights:")
    for strategy, params in state.items():
        alpha = params['alpha']
        beta = params['beta']
        mean = alpha / (alpha + beta)
        samples = alpha + beta - 2  # Subtract initial alpha=1, beta=1
        print(f"  • {strategy:12s}: α={alpha:6.2f}, β={beta:6.2f}, mean={mean:.3f}, samples={samples:.0f}")

    print(f"\n📌 This state will be automatically loaded on backend startup")
    print(f"   if cache/smart_bandit_state.json doesn't exist")

    return 0

if __name__ == "__main__":
    exit(main())
