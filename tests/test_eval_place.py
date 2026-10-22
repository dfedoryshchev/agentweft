import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.evals import harness, recording
from agentweft.providers import fake_provider
from agentweft.runner import prompts

FLOW = "fix-with-test"
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
REPLIES = {
    "worker.md": [{"say": "FAILS: assert -1 == 3\nTEST: test_calc.py\n\n"
                          + TEST,
                   "writes": {"test_calc.py": TEST}}],
    "patcher.md": [{"say": "TEST: test_calc.py\n\n-    return a - b\n"
                           "+    return a + b\n",
                    "writes": {"calc.py": FIXED}}]}
PATH = ["worker.md ok -> patcher.md  PASS red-test",
        "patcher.md ok  PASS red-test  PASS red-first  PASS command",
        "retro.md ok"]


@pytest.fixture
def case_dir(tmp_path, monkeypatch):
    """an evals folder with one fix-with-test case that brings its own place:
    a calc.py that subtracts, and step answers that write the test and the
    fix."""
    root = tmp_path / "evals"
    case = root / FLOW / "cases" / "clean-fix"
    (case / "place").mkdir(parents=True)
    (case / "place" / "calc.py").write_text(BUGGY, encoding="utf-8")
    (case / "case.yaml").write_text(yaml.safe_dump(
        {"task": "add(1, 2) returns -1", "place": "place",
         "provider": {"provider": "fake", "replies": REPLIES},
         "expect": {"invariants": "all",
                    "steps": {"match": "strict", "path": PATH}}}),
        encoding="utf-8")
    monkeypatch.setattr(harness, "ROOT", root)
    monkeypatch.setattr(harness, "LAST", root / ".last.json")
    return case


def ran(case_dir, record=False):
    case = harness.load_case(case_dir)
    out = harness.run_flow_for(FLOW, case, record=record)
    return case, out


def test_a_case_with_a_place_runs_its_gates_there_and_ends_done(case_dir):
    case, out = ran(case_dir)
    assert out[2] == ""
    scored = harness.score(runner.config(FLOW), *out, steps=out.steps,
                           expect=case["expect"])
    steps_row = [r for r in scored["rows"]
                 if r["invariant"].startswith("the steps it took")][0]
    assert steps_row["ok"], steps_row["detail"]


def test_red_first_replays_the_start_of_the_place(case_dir, capsys):
    """the copy is a git work tree holding the case's files as one commit, so
    the red-first gate replays the start instead of passing unrun."""
    _, out = ran(case_dir)
    assert out[2] == ""
    printed = capsys.readouterr().out
    first = [l for l in printed.split("\n") if "red-first" in l]
    assert first and "not replayed" not in first[0]


def test_the_place_is_a_copy_and_the_repo_tree_is_untouched(case_dir):
    here = Path(".").resolve()
    before = sorted(p.name for p in here.iterdir())
    ran(case_dir)
    assert sorted(p.name for p in here.iterdir()) == before
    assert not (here / "calc.py").exists()
    assert not (here / "test_calc.py").exists()
    place = case_dir / "place"
    assert sorted(p.name for p in place.iterdir()) == ["calc.py"]
    assert (place / "calc.py").read_text(encoding="utf-8") == BUGGY


def test_a_recording_keeps_the_writes_and_replays_them(case_dir, monkeypatch):
    _, live = ran(case_dir, record=True)
    assert live[2] == ""
    blob = json.loads((case_dir / recording.FILE).read_text(encoding="utf-8"))
    wrote = {c["step"]: c.get("writes") for c in blob["calls"]}
    assert wrote == {"worker.md": {"test_calc.py": TEST},
                     "patcher.md": {"calc.py": FIXED}, "retro.md": None}
    assert (case_dir / "place" / "calc.py").read_text(
        encoding="utf-8") == BUGGY

    def ask(self, prompt, timeout=None):
        raise AssertionError("a replayed case called its provider")
    monkeypatch.setattr(fake_provider.FakeProvider, "ask", ask)
    case, out = ran(case_dir)
    assert case["recording"] is not None
    assert out[2] == ""
    assert [took["step"] for took in out.steps] == ["worker.md", "patcher.md",
                                                    "retro.md"]
    assert [g["ok"] for took in out.steps for g in took["gates"]] == [True] * 4


def test_the_fake_answers_each_step_from_its_own_list(tmp_path):
    fake = fake_provider.FakeProvider(replies={
        "a.md": ["one", {"say": "two", "writes": {"d/x.txt": "hi\n"}}],
        "b.md": ["bee"]})
    fake.where = tmp_path
    fake.at("a.md", None)
    assert fake.ask("p").text == "one"
    fake.at("b.md", None)
    assert fake.ask("p").text == "bee"
    fake.at("a.md", None)
    reply = fake.ask("p")
    assert reply.text == "two"
    assert reply.writes == {"d/x.txt": "hi\n"}
    assert (tmp_path / "d" / "x.txt").read_text(encoding="utf-8") == "hi\n"
    # past the end of a step's list, its last answer is given again
    assert fake.ask("p").text == "two"


def test_a_write_outside_the_place_is_refused(tmp_path):
    fake = fake_provider.FakeProvider(replies={
        "a.md": [{"say": "x", "writes": {"../out.txt": "no\n"}}]})
    fake.where = tmp_path / "place"
    fake.where.mkdir()
    fake.at("a.md", None)
    with pytest.raises(ValueError):
        fake.ask("p")
    assert not (tmp_path / "out.txt").exists()


def test_a_case_place_that_is_not_there_does_not_run(case_dir):
    cfg = yaml.safe_load((case_dir / "case.yaml").read_text(encoding="utf-8"))
    cfg["place"] = "nowhere"
    (case_dir / "case.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    _, out = ran(case_dir)
    assert "nowhere" in out[2]
    assert out.steps == []


def test_a_fake_with_no_place_does_not_write_where_it_was_started(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = fake_provider.FakeProvider(replies={
        "a.md": [{"say": "x", "writes": {"calc.py": FIXED}}]})
    fake.where = None
    fake.at("a.md", None)
    with pytest.raises(ValueError):
        fake.ask("p")
    assert not (tmp_path / "calc.py").exists()


def test_a_case_that_scripts_writes_and_has_no_place_does_not_run(
        case_dir, tmp_path, monkeypatch):
    cfg = yaml.safe_load((case_dir / "case.yaml").read_text(encoding="utf-8"))
    del cfg["place"]
    (case_dir / "case.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    started = tmp_path / "started"
    started.mkdir()
    monkeypatch.setattr(prompts, "FLOW_ROOT",
                        [str(Path("flows").resolve())])
    monkeypatch.chdir(started)
    _, out = ran(case_dir)
    assert "writes" in out[2] and "place" in out[2]
    assert out.steps == []
    assert list(started.iterdir()) == []


def test_a_replayed_case_with_writes_and_no_place_does_not_run(
        case_dir, tmp_path, monkeypatch):
    _, live = ran(case_dir, record=True)
    assert live[2] == ""
    cfg = yaml.safe_load((case_dir / "case.yaml").read_text(encoding="utf-8"))
    del cfg["place"]
    cfg["provider"] = {"provider": "fake"}
    (case_dir / "case.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    started = tmp_path / "started"
    started.mkdir()
    monkeypatch.setattr(prompts, "FLOW_ROOT",
                        [str(Path("flows").resolve())])
    monkeypatch.chdir(started)
    case, out = ran(case_dir)
    assert case["recording"] is not None
    assert "writes" in out[2] and "place" in out[2], out[2]
    assert out.steps == []
    assert list(started.iterdir()) == []
