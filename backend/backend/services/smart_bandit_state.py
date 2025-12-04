state = {
    "enabled": False,
    "started": False,
    "done": False,
    "last_error": None,
    "total": 0,
    "completed": 0,
    "cold_start": False,  # True if bandit started with uniform priors (no weights file)
}


def set_enabled(flag: bool) -> None:
    state["enabled"] = bool(flag)


def mark_started() -> None:
    state["started"] = True
    state["done"] = False
    state["completed"] = 0


def mark_done() -> None:
    state["done"] = True


def mark_error(err: str) -> None:
    state["last_error"] = str(err) if err else None


def mark_total(total: int) -> None:
    state["total"] = max(0, int(total))


def increment_completed() -> None:
    state["completed"] += 1
    if state["total"] > 0 and state["completed"] >= state["total"]:
        state["done"] = True


def set_cold_start(is_cold: bool) -> None:
    """Mark whether bandit started with cold uniform priors (no weights file)."""
    state["cold_start"] = bool(is_cold)


def get_status():
    return state.copy()
