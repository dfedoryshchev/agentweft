"""a red step that names a whole test file holding tests the run started
with is held to the tests it added there, by id, and so is every step after
it: a start test in the same file is never handed on as one it was given."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.guardrails.gates import redtest_gate
from agentweft.providers import cli_provider, fake_provider
from agentweft.runner import engine, prompts, resume, state

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"
BROKEN = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return sum((a, b))" + NL
START = ("from calc import add" + NL + NL + NL + "def test_add_order():" + NL
         + "    assert add(3, 1) == 2" + NL)
ADDED = START + NL + NL + "def test_add():" + NL \
    + "    assert add(1, 2) == 3" + NL
WORKER = "FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py" + NL
IDS = "tests/test_calc.py::test_add"


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_place(where):
    (where / "tests").mkdir(parents=True)
    for rel, text in (("calc.py", BROKEN), ("conftest.py", ""),
                      ("tests/test_calc.py", START)):
        (where / rel).write_text(text, encoding="utf-8")
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    git(where, "config", "commit.gpgsign", "false")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def run_it(tmp_path, monkeypatch, patcher):
    place = a_place(tmp_path / "project")
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.setdefault(step, []).append(prompt)
        if step == "worker.md":
            (place / "tests" / "test_calc.py").write_text(ADDED,
                                                          encoding="utf-8")
            return WORKER, False
        if step == "patcher.md":
            (place / "calc.py").write_text(FIXED, encoding="utf-8")
            return patcher, False
        return fake_provider.NOTHING_TO_KEEP, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--flows", str(FLOWS),
                                      "--workdir", str(place),
                                      "--task", "add(1, 2) returns -1"])
    engine.main()
    written = "".join((p / "gates.md").read_text(encoding="utf-8")
                      for p in (tmp_path / "runs").iterdir()
                      if (p / "gates.md").exists())
    return sent, written


def test_a_whole_file_named_red_is_handed_on_as_the_tests_added_to_it(
        tmp_path, monkeypatch):
    sent, written = run_it(tmp_path, monkeypatch, "return a + b")
    worker = written.split("## worker.md")[1].split("## ")[0]
    assert "PASS red-test" in worker
    patcher = sent["patcher.md"][0]
    assert "TEST: " + IDS in patcher
    assert "TEST: tests/test_calc.py" + NL not in patcher
    held = written.split("## patcher.md")[1].split("## ")[0]
    assert "PASS red-test - green" in held


def test_a_patcher_naming_the_same_whole_file_is_held_to_the_same_ids(
        tmp_path, monkeypatch):
    sent, written = run_it(tmp_path, monkeypatch,
                           "TEST: tests/test_calc.py" + NL + "return a + b")
    held = written.split("## patcher.md")[1].split("## ")[0]
    assert "PASS red-test - green" in held


def test_a_line_of_ids_reads_as_every_one_of_them():
    named, name, why = redtest_gate.read_test(
        "TEST: tests/a.py::test_x tests/a.py::T::test_y" + NL)
    assert (named, name, why) == ("tests/a.py::test_x tests/a.py::T::test_y",
                                  "", "")


def test_prose_with_spaces_is_still_refused_rather_than_split():
    named, _, why = redtest_gate.read_test("TEST: tests/a.py and the rest\n")
    assert named == "" and why
