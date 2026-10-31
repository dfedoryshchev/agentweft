"""the planner may name test coverage it sees missing, one `coverage:` line
each. the step that writes the tests is handed them to steer its cases, its
own cases standing; no other step is; the planner writes no test; and the
retro is handed them to keep as nice-to-do tickets for what the run left
uncovered."""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.runner import engine
from test_facts_attached import a_run, asked, put
from test_stops import CLAUDE, answer, steps_of, the_folder

NL = chr(10)
PLAN = ("- behaviour: an empty line raises" + NL + "  file: pkg/a.py" + NL + NL
        + "coverage: pkg/a.py - no test reads a line of only spaces" + NL)
STEER = "test coverage the planner names as missing"
PLANNER = "planner" + NL + "writes: none"
TESTER = NL.join(["tester", "writes: tests", "gates:", "  - gate: red-test",
                  "    red: true",
                  "    command: [python, -c, 'raise SystemExit(1)']"])
WORKER = "reviewer" + NL + "writes: none"


def test_the_tester_is_handed_the_coverage_the_planner_names(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "pkg/a.py", "x = 1" + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, [PLANNER, TESTER],
                 answer(PLAN), answer("done" + NL),
                 task="make pkg/a.py stricter")
    engine.main()
    tester = asked(fake)[1]
    assert STEER in tester
    part = tester.split(STEER)[1]
    assert "- pkg/a.py: no test reads a line of only spaces" in part
    assert "your own cases stand" in part
    assert steps_of(the_folder())[0]["coverage"] == [
        {"file": "pkg/a.py", "what": "no test reads a line of only spaces"}]


def test_a_step_that_writes_no_tests_is_not_handed_it(tmp_path, monkeypatch,
                                                      fake_cli):
    put(tmp_path, "pkg/a.py", "x = 1" + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, [PLANNER, WORKER],
                 answer(PLAN), answer("done" + NL),
                 task="make pkg/a.py stricter")
    engine.main()
    assert STEER not in asked(fake)[1]


def test_with_no_coverage_line_nothing_is_handed(tmp_path, monkeypatch,
                                                 fake_cli):
    put(tmp_path, "pkg/a.py", "x = 1" + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, [PLANNER, TESTER],
                 answer("- behaviour: x" + NL), answer("done" + NL),
                 task="make pkg/a.py stricter")
    engine.main()
    assert STEER not in asked(fake)[1]
    assert "coverage" not in steps_of(the_folder())[0]


def test_the_retro_is_handed_the_coverage_to_keep_as_tickets(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "pkg/a.py", "x = 1" + NL)
    fake = a_run(tmp_path, monkeypatch, fake_cli, [PLANNER, WORKER],
                 answer(PLAN), answer("done" + NL),
                 answer("## change first" + NL + "- none" + NL),
                 task="make pkg/a.py stricter", head="retro: true" + NL)
    engine.main()
    retro = asked(fake)[-1]
    assert ("- seq 1 planner.md: pkg/a.py - no test reads a line of only"
            " spaces") in retro
    assert "nice-to-do" in retro.split("seq 1 planner.md: pkg/a.py")[0][-400:]


def test_the_shipped_planner_is_told_it_may_name_coverage():
    said = (Path("flows") / "build-feature" / "planner.md").read_text(
        encoding="utf-8")
    assert "coverage: <file> - " in said
    assert "you write no test" in said
