import sys

sys.path.insert(0, ".")
import runner


def test_remaining_starts_at_the_failed_step():
    steps = ["planner.md", "worker.md", "merge.md", "reviewer.md"]
    assert runner.remaining(steps, "merge.md") == ["merge.md", "reviewer.md"]


def test_remaining_is_everything_when_the_step_is_unknown():
    steps = ["worker.md", "reviewer.md"]
    assert runner.remaining(steps, "gone.md") == steps
