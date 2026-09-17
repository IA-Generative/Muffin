from app.graph.state import ResearchTask


def compute_ready_and_blocked(
    tasks: list[ResearchTask], completed_ids: set[str], running_or_done_ids: set[str]
) -> tuple[list[ResearchTask], list[ResearchTask]]:
    """A task is ready once every one of its dependencies is in `completed_ids` (§8/§27) - never
    before, so e.g. a comparison task can't start reading its inputs while they're still running."""
    ready, blocked = [], []
    for task in tasks:
        if task["id"] in running_or_done_ids:
            continue
        if all(dep in completed_ids for dep in task["dependencies"]):
            ready.append(task)
        else:
            blocked.append(task)
    return ready, blocked
