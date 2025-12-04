#!/usr/bin/env python3
"""
Manage Smart RAG Thompson Sampling bandit state.

功能:
- 查看当前 bandit 权重
- 重置 bandit 到初始状态
- 导出/导入 bandit 状态

Usage:
  python scripts/manage_bandit_state.py view
  python scripts/manage_bandit_state.py reset
  python scripts/manage_bandit_state.py export backup.json
  python scripts/manage_bandit_state.py import backup.json
"""

import argparse
import json
import os
from pathlib import Path


DEFAULT_STATE_FILE = "./cache/smart_bandit_state.json"


def view_state(state_file: str = DEFAULT_STATE_FILE):
    """查看当前 bandit 状态"""
    print("=" * 80)
    print("Smart RAG Bandit State")
    print("=" * 80)

    if not os.path.exists(state_file):
        print(f"\n⚠️  State file not found: {state_file}")
        print("Bandit has not been trained yet (using default state)")
        print_default_state()
        return

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)

        print(f"\nState file: {state_file}")
        print(f"Last modified: {Path(state_file).stat().st_mtime}")
        print()

        print("Strategy Weights (Beta Distribution Parameters):")
        print("-" * 80)
        print(f"{'Strategy':<15} {'Alpha':<10} {'Beta':<10} {'Trials':<10} {'Win Rate':<10}")
        print("-" * 80)

        for strategy, params in sorted(state.items()):
            alpha = params.get("alpha", 1.0)
            beta = params.get("beta", 1.0)
            trials = alpha + beta - 2.0
            win_rate = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5

            print(f"{strategy:<15} {alpha:<10.2f} {beta:<10.2f} {trials:<10.0f} {win_rate:<10.2%}")

        print()
        print("💡 Interpretation:")
        print("  - Alpha: Accumulated 'success' (high reward)")
        print("  - Beta: Accumulated 'failure' (low reward)")
        print("  - Trials: Total number of times this strategy was selected")
        print("  - Win Rate: Expected probability of success (alpha / (alpha + beta))")
        print()

    except Exception as e:
        print(f"❌ Error reading state file: {e}")


def print_default_state():
    """打印默认初始状态"""
    default_state = {
        "hybrid": {"alpha": 1.0, "beta": 1.0},
        "iterative": {"alpha": 1.0, "beta": 1.0},
        "graph": {"alpha": 1.0, "beta": 1.0},
        "table": {"alpha": 1.0, "beta": 1.0},
    }

    print("\nDefault Initial State:")
    print("-" * 80)
    print(f"{'Strategy':<15} {'Alpha':<10} {'Beta':<10} {'Trials':<10} {'Win Rate':<10}")
    print("-" * 80)

    for strategy, params in sorted(default_state.items()):
        print(f"{strategy:<15} {params['alpha']:<10.2f} {params['beta']:<10.2f} {0.0:<10.0f} {0.5:<10.2%}")


def reset_state(state_file: str = DEFAULT_STATE_FILE, confirm: bool = False):
    """重置 bandit 到初始状态"""
    print("=" * 80)
    print("Reset Smart RAG Bandit State")
    print("=" * 80)

    if os.path.exists(state_file) and not confirm:
        print(f"\n⚠️  Warning: This will delete the learned bandit state!")
        print(f"State file: {state_file}")
        response = input("\nAre you sure? (yes/no): ")
        if response.lower() != "yes":
            print("Reset cancelled.")
            return

    # Remove existing state file
    if os.path.exists(state_file):
        os.remove(state_file)
        print(f"\n✅ Deleted state file: {state_file}")
    else:
        print(f"\n✅ No state file found (already at default state)")

    print("\nBandit will use default initial state on next restart:")
    print_default_state()


def export_state(state_file: str = DEFAULT_STATE_FILE, output_file: str = "bandit_backup.json"):
    """导出 bandit 状态到备份文件"""
    print("=" * 80)
    print("Export Smart RAG Bandit State")
    print("=" * 80)

    if not os.path.exists(state_file):
        print(f"\n⚠️  State file not found: {state_file}")
        print("Nothing to export.")
        return

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)

        with open(output_file, 'w') as f:
            json.dump(state, f, indent=2)

        print(f"\n✅ Exported bandit state to: {output_file}")
        print(f"Source: {state_file}")
        print(f"Size: {os.path.getsize(output_file)} bytes")

    except Exception as e:
        print(f"❌ Error exporting state: {e}")


def import_state(state_file: str = DEFAULT_STATE_FILE, input_file: str = "bandit_backup.json"):
    """从备份文件导入 bandit 状态"""
    print("=" * 80)
    print("Import Smart RAG Bandit State")
    print("=" * 80)

    if not os.path.exists(input_file):
        print(f"\n⚠️  Backup file not found: {input_file}")
        return

    try:
        with open(input_file, 'r') as f:
            state = json.load(f)

        # Validate state structure
        required_keys = {"hybrid", "iterative", "graph", "table"}
        if not required_keys.issubset(state.keys()):
            print(f"❌ Invalid state file: missing required strategies")
            return

        for strategy, params in state.items():
            if "alpha" not in params or "beta" not in params:
                print(f"❌ Invalid state file: {strategy} missing alpha/beta")
                return

        # Save to state file
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)

        print(f"\n✅ Imported bandit state from: {input_file}")
        print(f"Target: {state_file}")
        print("\nImported state:")
        view_state(state_file)

    except Exception as e:
        print(f"❌ Error importing state: {e}")


def main():
    parser = argparse.ArgumentParser(description="Manage Smart RAG bandit state")
    parser.add_argument("command", choices=["view", "reset", "export", "import"],
                        help="Command to execute")
    parser.add_argument("file", nargs='?', help="File for export/import")
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE,
                        help="Path to bandit state file")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompts")

    args = parser.parse_args()

    if args.command == "view":
        view_state(args.state_file)

    elif args.command == "reset":
        reset_state(args.state_file, confirm=args.yes)

    elif args.command == "export":
        output_file = args.file or "bandit_backup.json"
        export_state(args.state_file, output_file)

    elif args.command == "import":
        if not args.file:
            print("Error: import requires a file argument")
            return
        import_state(args.state_file, args.file)


if __name__ == "__main__":
    main()
