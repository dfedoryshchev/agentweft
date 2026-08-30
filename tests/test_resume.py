import datetime
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.runner import engine, resume


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


def a_parked_journal(tmp_path, monkeypatch, step="reviewer.md",
                     run_id="demo-flow-2026-08-30-152241"):
    """park a run the way the engine parks one, and read it back the way the
    resume reads it, so the two halves are pinned against each other rather
    than against a line typed out by hand.
    """
    monkeypatch.chdir(tmp_path)
    engine.journal("demo flow", "parked at " + step, datetime.datetime.now(),
                   run_id)
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")


def test_a_parked_run_reads_back_as_parked_and_not_as_a_failure(tmp_path,
                                                                monkeypatch):
    a_parked_journal(tmp_path, monkeypatch)
    stop = resume.last_stop("demo flow")
    assert stop.parked
    assert stop.step == "reviewer.md"
    # a park is not a failure, and must not answer the question asking for one
    assert resume.last_failure("demo flow") is None


def test_a_run_that_died_and_a_run_that_parked_are_told_apart(tmp_path,
                                                              monkeypatch):
    j = tmp_path / "journal.md"
    monkeypatch.setattr(resume, "JOURNAL", j)
    j.write_text("2026-08-30 15:22  demo flow  failed at worker.md  12s\n")
    assert resume.last_stop("demo flow").kind == "failed"
    assert not resume.last_stop("demo flow").parked
    j.write_text("2026-08-30 15:22  demo flow  parked at worker.md  12s  demo-1\n")
    assert resume.last_stop("demo flow").kind == "parked"
    assert resume.last_stop("demo flow").parked


def test_a_park_picks_up_after_the_step_and_a_failure_picks_up_at_it():
    # the parked step finished and passed its checks; the step that died left
    # nothing behind, so it is the one place the two answers differ
    steps = ["planner.md", "worker.md", "reviewer.md"]
    assert resume.after(steps, "worker.md") == ["reviewer.md"]
    assert resume.remaining(steps, "worker.md") == ["worker.md", "reviewer.md"]


def test_nothing_is_left_when_the_step_that_parked_was_the_last_one():
    assert resume.after(["planner.md", "reviewer.md"], "reviewer.md") == []


def test_after_is_everything_when_the_step_is_unknown():
    steps = ["worker.md", "reviewer.md"]
    assert resume.after(steps, "gone.md") == steps


def test_the_parked_line_keeps_the_run_id_for_the_person_reading_it(tmp_path,
                                                                    monkeypatch):
    """the step is what the resume arithmetic runs on. the run id is which
    folder to go and look in, and it rides in the last column rather than
    coming back as part of the Stop.
    """
    a_parked_journal(tmp_path, monkeypatch)
    line = (tmp_path / "runs" / "journal.md").read_text().strip()
    assert line.split("  ")[1] == "demo flow"
    assert line.split("  ")[2] == "parked at reviewer.md"
    assert line.split("  ")[-1] == "demo-flow-2026-08-30-152241"


def test_the_run_to_pick_up_is_the_newest_one_of_that_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ["demo-2026-08-29-1", "demo-2026-08-30-1", "other-2026-08-30-1"]:
        (tmp_path / "runs" / name).mkdir(parents=True)
    assert resume.runs_for("demo") == ["demo-2026-08-29-1", "demo-2026-08-30-1"]
    assert resume.runs_for("demo")[-1] == "demo-2026-08-30-1"


def test_what_the_parked_step_produced_is_read_back_as_utf8(tmp_path, monkeypatch):
    # a digest with one smart quote in it came back as a UnicodeDecodeError,
    # and only ever on resume
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "runs" / "demo-1"
    folder.mkdir(parents=True)
    smart = "it" + chr(8217) + "s fine"
    (folder / "reviewer.md").write_text(smart, encoding="utf-8")
    assert resume.step_output("demo-1", "reviewer.md") == smart


def test_a_step_that_left_nothing_behind_reads_as_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resume.step_output("demo-1", "gone.md") == ""
