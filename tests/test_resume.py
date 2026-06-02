import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.runner import resume


def test_remaining_starts_at_the_failed_step():
    steps = ["planner.md", "worker.md", "merge.md", "reviewer.md"]
    assert runner.remaining(steps, "merge.md") == ["merge.md", "reviewer.md"]


def test_remaining_is_everything_when_the_step_is_unknown():
    steps = ["worker.md", "reviewer.md"]
    assert runner.remaining(steps, "gone.md") == steps


def test_last_failure_reads_the_journal(tmp_path, monkeypatch):
    j = tmp_path / "journal.md"
    j.write_text("2025-11-20 09:00  weekly digest  failed at merge.md  12s\n")
    monkeypatch.setattr(resume, "JOURNAL", j)
    assert resume.last_failure("weekly digest")[0] == "merge.md"


def test_a_later_good_run_clears_the_failure(tmp_path, monkeypatch):
    j = tmp_path / "journal.md"
    j.write_text("2025-11-20 09:00  weekly digest  failed at merge.md  12s\n"
                 "2025-11-20 10:00  weekly digest  ok  40s  x.md\n")
    monkeypatch.setattr(resume, "JOURNAL", j)
    assert resume.last_failure("weekly digest") is None
