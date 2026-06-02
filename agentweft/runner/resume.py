"""rerun a flow from the step that died, using the journal to find it."""
from pathlib import Path

JOURNAL = Path("runs") / "journal.md"


def last_failure(flow_name):
    """-> (step, when) of the most recent failed run for this flow, or None."""
    if not JOURNAL.exists():
        return None
    found = None
    for line in JOURNAL.read_text().split("\n"):
        if not line.strip():
            continue
        parts = [p for p in line.split("  ") if p]
        if len(parts) < 3 or parts[1] != flow_name:
            continue
        if parts[2].startswith("failed at "):
            found = (parts[2][len("failed at "):], parts[0])
        else:
            # a later good run means there is nothing to pick up
            found = None
    return found


def step_output(run_id, step):
    p = Path("runs") / run_id / step
    return p.read_text(encoding="utf-8") if p.exists() else ""


def runs_for(flow):
    runs = Path("runs")
    if not runs.exists():
        return []
    return sorted(p.name for p in runs.iterdir() if p.is_dir() and p.name.startswith(flow + "-"))


def remaining(all_steps, failed_step):
    if failed_step not in all_steps:
        return all_steps
    return all_steps[all_steps.index(failed_step):]
