"""a gate is turned off for one run by name and with a reason, and the run
records which one and why."""
import json
import sys

sys.path.insert(0, ".")
from agentweft.runner import stops

from test_red_order import (FIXED, NL, TESTER, WORKER, a_flow, a_repo,
                            folders, read, running)

SKIPS = "skips.json"
NEVER = ("    gates:" + NL + "      - gate: regex" + NL
         + "        pattern: \"never said\"" + NL)
GATED = ("  - role: worker" + NL + "    prompt: worker.md" + NL + NEVER)


def gate_lines(folder):
    out = []
    for line in read(folder / "steps.jsonl").splitlines():
        out.extend(json.loads(line).get("gates") or [])
    return out


def test_a_named_gate_is_not_run_and_the_record_says_why(tmp_path,
                                                         monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", GATED)
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")},
                           "--skip", "regex", "the pattern is wrong")
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    folder = folders()[-1]
    decided = read(folder / "decisions.md")
    assert "regex" in decided and "the pattern is wrong" in decided
    handoff = read(folder / "handoff.md")
    assert "regex" in handoff and "the pattern is wrong" in handoff
    said = [g for g in gate_lines(folder) if g["gate"] == "regex"]
    assert said and "the pattern is wrong" in said[0]["detail"]
    assert json.loads(read(folder / SKIPS)) == {
        "regex": "the pattern is wrong"}


def test_without_the_skip_the_gate_still_holds(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", GATED)
    code, _ = running(tmp_path, monkeypatch, place, "build",
                      {"worker.md": ({}, "done")})
    assert code == stops.exit_code(stops.GATE)


def test_a_skip_with_no_reason_is_refused(tmp_path, monkeypatch, capsys):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", GATED)
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")}, "--skip", "regex")
    assert code == 1
    assert called == []
    assert "needs a reason" in capsys.readouterr().out


def test_an_unknown_gate_name_is_refused(tmp_path, monkeypatch, capsys):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", GATED)
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")},
                           "--skip", "regex,no-such-gate", "because")
    assert code == 1
    assert called == []
    assert "no-such-gate" in capsys.readouterr().out


def test_a_gate_the_flow_does_not_have_is_refused(tmp_path, monkeypatch,
                                                  capsys):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", GATED)
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")},
                           "--skip", "length", "because")
    assert code == 1
    assert called == []
    assert "length" in capsys.readouterr().out


def test_skip_tests_is_the_same_as_skipping_tests_by_name(tmp_path,
                                                          monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({}, "no test for a hotfix"),
        "worker.md": ({"calc.py": FIXED}, "done")},
        "--skip", "tests", "hotfix")
    assert called == ["tester.md", "worker.md"]
    assert code == stops.EXIT_OK
    folder = folders()[-1]
    assert "hotfix" in read(folder / "decisions.md")
    assert "tests skipped: hotfix" in read(folder / "handoff.md")
    said = [g for g in gate_lines(folder) if g["gate"] == "red-test"]
    assert said and "hotfix" in said[0]["detail"]


def test_a_resumed_run_skips_the_same_gates(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", GATED + "      - gate: length" + NL
           + "        max_lines: 1" + NL)
    code, _ = running(tmp_path, monkeypatch, place, "build",
                      {"worker.md": ({}, "one" + NL + "two" + NL)},
                      "--skip", "regex", "the pattern is wrong")
    assert code == stops.exit_code(stops.GATE)
    first = folders()[-1].name
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")}, "--resume", first)
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    assert json.loads(read(folders()[-1] / SKIPS)) == {
        "regex": "the pattern is wrong"}


def test_a_gate_named_twice_is_refused(tmp_path, monkeypatch, capsys):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", GATED)
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({}, "done")},
                           "--skip", "regex", "one", "--skip", "regex", "two")
    assert code == 1
    assert called == []
    assert "twice" in capsys.readouterr().out


def test_skips_and_skip_tests_go_together(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + GATED.replace(
        "    prompt: worker.md" + NL, "    prompt: worker.md" + NL
        + "    writes: product" + NL))
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({}, "no test for a hotfix"),
        "worker.md": ({"calc.py": FIXED}, "done")},
        "--skip-tests", "hotfix", "--skip", "regex", "the pattern is wrong")
    assert called == ["tester.md", "worker.md"]
    assert code == stops.EXIT_OK
    assert json.loads(read(folders()[-1] / SKIPS)) == {
        "regex": "the pattern is wrong", "tests": "hotfix"}
