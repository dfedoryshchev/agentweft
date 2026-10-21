"""a run that stops before green names the tests it leaves red.

a stop can be right and still leave a test the run wrote failing in the tree:
the patcher stops on a spec conflict after the worker appended a red test to a
supplied file. the handoff said `changed: 1 file` and nothing about it being
red. on any stop the runner now runs the tests the run added or changed since
it started, once, and names each red one in the handoff and on the console.
nothing is reverted unless the run asks: `on_stop: revert-tests` in the flow,
or `--on-stop revert-tests` on the command line, puts the test files back to
their bytes at the start and says so.

the flow is the shipped fix-with-test, on fake answers and a real git place.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.providers import cli_provider
from agentweft.runner import engine, prompts, resume, state, stops

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_place(where, files):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    git(where, "config", "commit.gpgsign", "false")
    for rel, text in files.items():
        path = where / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return dict((rel, (where / rel).read_bytes()) for rel in files)


def go(tmp_path, monkeypatch, flow, said, edits, *extra):
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        n = asked.count(step)
        asked.append(step)
        edits(step, n)
        got = said.get(step, [""])
        return got[min(n, len(got) - 1)], False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", flow, "--force", "--flows",
                                      str(FLOWS), "--workdir", "project"]
                        + list(extra))
    return asked, engine.main()


def handoff_of(tmp_path):
    [folder] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    return (folder / "handoff.md").read_text(encoding="utf-8")


def needs_you(text):
    return text.split("## needs you", 1)[1].split("## assumed", 1)[0]


SPEC = ("# export" + NL
        + "in the JSON export, `amount` is a string with 2 decimals." + NL)
EXPORT = ("import json" + NL + NL + NL + "def export(amount):" + NL
          + "    return json.dumps({'amount': '%.2f' % amount})" + NL)
SUPPLIED = ("import json" + NL + NL + "from export import export" + NL
            + NL + NL + "def test_export_json():" + NL
            + "    assert json.loads(export(-25))['amount'] == '-25.00'" + NL)
APPENDED = (NL + NL + "def test_amount_is_a_number():" + NL
            + "    assert json.loads(export(-25))['amount'] == -25" + NL)
BUG = ("Bug report: export writes amounts as strings. Amounts in the JSON"
       " export must be JSON numbers.")
WORKER = ("FAILS: assert '-25.00' == -25" + NL
          + "TEST: tests/test_export.py::test_amount_is_a_number" + NL)
CONFLICT = ('CONFLICT: TASK.md:2 "`amount` is a string with 2 decimals"' + NL
            + "request: Amounts in the JSON export must be JSON numbers" + NL)
RED_ID = "tests/test_export.py::test_amount_is_a_number"


def place_of(tmp_path):
    return a_place(tmp_path / "project", {
        "TASK.md": SPEC, "export.py": EXPORT, "conftest.py": "",
        "tests/test_export.py": SUPPLIED})


def appends(place):
    def edits(step, n):
        if step == "worker.md":
            (place / "tests" / "test_export.py").write_text(
                SUPPLIED + APPENDED, encoding="utf-8")
    return edits


ANSWERS = {"worker.md": [WORKER], "patcher.md": [CONFLICT]}


def test_a_conflict_stop_names_the_test_it_leaves_red(tmp_path, monkeypatch,
                                                      capsys):
    place_of(tmp_path)
    place = tmp_path / "project"
    asked, code = go(tmp_path, monkeypatch, "fix-with-test", ANSWERS,
                     appends(place), "--task", BUG)
    assert asked == ["worker.md", "patcher.md"]
    assert code == stops.EXIT_STOP
    text = handoff_of(tmp_path)
    changed = [l for l in text.split(NL) if l.startswith("changed: ")][0]
    assert "1 test the run added or changed is red" in changed
    section = needs_you(text)
    assert "- " + RED_ID + ": red" in section
    assert "test_export_json" not in section
    assert "nothing was reverted" in section
    printed = capsys.readouterr().out
    assert RED_ID + ": red" in printed
    # never reverted by default
    assert (place / "tests" / "test_export.py").read_text(
        encoding="utf-8") == SUPPLIED + APPENDED


def test_revert_tests_puts_the_test_files_back_to_their_bytes_at_the_start(
        tmp_path, monkeypatch):
    before = place_of(tmp_path)
    place = tmp_path / "project"

    def edits(step, n):
        appends(place)(step, n)
        if step == "worker.md":
            (place / "tests" / "test_more.py").write_text(
                "def test_more():" + NL + "    assert False" + NL,
                encoding="utf-8")

    go(tmp_path, monkeypatch, "fix-with-test", ANSWERS, edits, "--task", BUG,
       "--on-stop", "revert-tests")
    assert (place / "tests" / "test_export.py").read_bytes() == \
        before["tests/test_export.py"]
    assert not (place / "tests" / "test_more.py").exists()
    section = needs_you(handoff_of(tmp_path))
    assert "- " + RED_ID + ": red" in section
    assert "on_stop: revert-tests" in section
    assert "tests/test_export.py" in section.split("revert-tests", 1)[1]
    assert git(place, "status", "--porcelain", "--", "tests").strip() == ""


def test_a_stop_with_no_new_tests_says_nothing_extra(tmp_path, monkeypatch):
    place_of(tmp_path)
    asked, code = go(tmp_path, monkeypatch, "fix-with-test",
                     {"worker.md": [CONFLICT]}, lambda s, n: None,
                     "--task", BUG)
    assert asked == ["worker.md"] and code == stops.EXIT_STOP
    text = handoff_of(tmp_path)
    assert "is red" not in text and "are red" not in text
    assert "reverted" not in text and "revert-tests" not in text


CALC_SPEC = "# calc" + NL + NL + "add(a, b) returns a plus b" + NL
BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL
OLD = ("from calc import add" + NL + NL + NL + "def test_old():" + NL
       + "    assert add(2, 2) == 0" + NL)
NEW = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
       + "    assert add(1, 2) == 3" + NL)
CLAIM = ("WRONG TEST: tests/test_old.py::test_old" + NL
         + "why: it wants add(2, 2) to be 0" + NL
         + 'spec: TASK.md:3 "add(a, b) returns a plus b"' + NL)
OLD_ID = "tests/test_old.py::test_old"


def test_a_start_test_the_stop_names_is_listed_as_red_now(tmp_path,
                                                          monkeypatch):
    a_place(tmp_path / "project", {"TASK.md": CALC_SPEC, "calc.py": BUGGY,
                                   "conftest.py": "",
                                   "tests/test_old.py": OLD})
    place = tmp_path / "project"

    def edits(step, n):
        if step == "worker.md":
            (place / "tests" / "test_add.py").write_text(NEW,
                                                         encoding="utf-8")
        if step == "patcher.md":
            (place / "calc.py").write_text(FIXED, encoding="utf-8")

    said = {"worker.md": ["FAILS: assert -1 == 3" + NL
                          + "TEST: tests/test_add.py::test_add" + NL],
            "patcher.md": [CLAIM]}
    asked, code = go(tmp_path, monkeypatch, "fix-with-test", said, edits,
                     "--task", "add(1, 2) returns -1")
    assert asked == ["worker.md", "patcher.md"] and code == stops.EXIT_STOP
    text = handoff_of(tmp_path)
    suite = [l for l in text.split(NL) if l.startswith("suite: ")][0]
    assert "red now: " + OLD_ID + " (a test the run started with)" in suite
    section = needs_you(text)
    assert ("red now, tests the run started with that the stop names (run"
            " once after the stop):") in section
    assert "- " + OLD_ID + ": red" in section


def test_a_start_test_the_stop_names_that_is_green_is_not_listed(
        tmp_path, monkeypatch):
    a_place(tmp_path / "project", {"TASK.md": CALC_SPEC, "calc.py": BUGGY,
                                   "conftest.py": "",
                                   "tests/test_old.py": OLD})
    place = tmp_path / "project"

    def edits(step, n):
        if step == "worker.md":
            (place / "tests" / "test_add.py").write_text(NEW,
                                                         encoding="utf-8")

    said = {"worker.md": ["FAILS: assert -1 == 3" + NL
                          + "TEST: tests/test_add.py::test_add" + NL],
            "patcher.md": [CLAIM]}
    go(tmp_path, monkeypatch, "fix-with-test", said, edits,
       "--task", "add(1, 2) returns -1")
    text = handoff_of(tmp_path)
    assert "red now" not in text


def test_on_stop_is_a_flow_key_with_two_values():
    raw = {"name": "x", "steps": [{"role": "a"}]}
    assert spec.check(dict(raw, on_stop="revert-tests")) == []
    assert spec.check(dict(raw, on_stop="keep")) == []
    assert any("on_stop" in c for c in spec.check(dict(raw, on_stop="drop")))


def test_the_command_line_choice_wins_over_the_flow(monkeypatch):
    assert importlib.util.find_spec("agentweft.runner.leftred") is not None
    from agentweft.runner import leftred

    fm = spec.load({"name": "x", "steps": [{"role": "a"}],
                    "on_stop": "revert-tests"})
    assert leftred.chosen(fm, ["run.py", "x"]) == leftred.REVERT
    assert leftred.chosen(fm, ["run.py", "x", "--on-stop", "keep"]) == \
        leftred.KEEP
    assert leftred.chosen(spec.load({"name": "x", "steps": [{"role": "a"}]}),
                          ["run.py", "x"]) == leftred.KEEP
