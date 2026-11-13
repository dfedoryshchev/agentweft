"""the handoff's changed, read, tests and retro sections are written by the
runner from git, the step transcripts and steps.jsonl, never from a step's
text."""
import json
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.runner import engine, handoff, stops, summary
from test_stops import CLAUDE, a_flow, answer, the_folder


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_repo(where):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    (where / "calc.py").write_text("def add(a, b):\n    return a - b\n",
                                   encoding="utf-8")
    (where / "notes.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (where / "TASK.md").write_text("# task\n\nadd adds.\n", encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def a_transcript(root, session, uses):
    """a cli transcript holding one tool call per (tool name, input)."""
    folder = root / "D--a-place"
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (name, given) in enumerate(uses):
        lines.append(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t" + str(i), "name": name,
             "input": given}]}}))
        lines.append(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t" + str(i),
             "content": "ok"}]}}))
    (folder / (session + ".jsonl")).write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")


WORKER = ("fixed it\n\nHANDOFF\nDID:\n- calc.py: add returns a + b\n"
          "READ:\n- calc.py:1-2 - add subtracts\n"
          "- docs/old.md:1-9 - the old notes\nEND HANDOFF\n")
REDO = "VERDICT: redo\n\nnotes.md still says three\n"
OK = "VERDICT: ok\n\nfine\n"


def section(note, name):
    return note.split("## " + name + "\n")[1].split("\n## ")[0]


def test_a_two_step_run_takes_changed_from_git_read_from_the_transcript(
        tmp_path, monkeypatch, fake_cli):
    place = a_repo(tmp_path / "repo")
    projects = tmp_path / "projects"
    a_transcript(projects, "w-1", [
        ("Read", {"file_path": str(place / "calc.py"), "offset": 1,
                  "limit": 2}),
        ("Bash", {"command": "cd " + place.as_posix()
                  + " && sed -n '1,3p' TASK.md 2>&1 | head -5"})])
    monkeypatch.setattr(handoff, "PROJECTS", projects)
    a_flow(tmp_path, monkeypatch, "two", ["worker", "reviewer"],
           tail="workdir: " + place.as_posix() + "\n" + CLAUDE)
    fake_cli(answer(WORKER, session="w-1"), answer(REDO, session="r-1"),
             answer(WORKER.replace("fixed it", "fixed the notes too"),
                    session="w-2"),
answer(OK, session="r-2"))
    real = engine.Run.step
    goes = []

    def step(self, name, *a, **kw):
        if name == "worker.md":
            goes.append(name)
            if len(goes) == 1:
                (place / "calc.py").write_text(
                    "def add(a, b):\n    return a + b\n", encoding="utf-8")
                git(place, "commit", "-qam", "fix add")
            else:
                (place / "notes.md").write_text("one\ntwo\n3\n",
                                                encoding="utf-8")
        return real(self, name, *a, **kw)

    monkeypatch.setattr(engine.Run, "step", step)
    assert engine.main() == 0
    note = (the_folder() / summary.FILE).read_text(encoding="utf-8")

    changed = section(note, "changed")
    assert "- calc.py +1 -1 (committed), lines 2" in changed
    assert "- notes.md +1 -1 (uncommitted), lines 3" in changed
    assert "- git status --short:\n     M notes.md" in changed
    log = changed.split("- git log --oneline ")[1].split("\n")
    assert log[0].endswith("..HEAD:")
    assert log[1].endswith(" fix add") and len(log[1].split()) == 3

    read = section(note, "read")
    assert "- worker.md read: calc.py:1-2; TASK.md:1-3" in read
    assert "  said: calc.py:1-2 - add subtracts" in read
    assert "  said, not in its transcript: docs/old.md:1-9 - the old notes" \
        in read
    assert "already read" not in note

    retro = section(note, "retro").split("\n")
    assert [l for l in retro if "sent the work back" in l] == [
        "- reviewer.md sent the work back: notes.md still says three"]
    steps = [l for l in retro if l.endswith(("no events", "sent back"))]
    assert [l.split(" ")[1] for l in steps] == [
        "worker.md", "reviewer.md", "worker.md", "reviewer.md"]
    assert all("($0.2500)" in l for l in steps)
    assert steps[1].endswith(": sent back")
    assert "sent the work back" not in section(note, "run")


def a_pass(step, outcome="ok", facts=None, said=""):
    return summary.a_pass(step, step.split(".")[0], 1.0, handoff.empty(), [],
                          False, outcome, said, facts=facts)


def test_retro_names_retries_limits_refusals_and_shell_trouble_per_step():
    lines = summary.retro([a_pass("worker.md", facts={
        "cost": 0.5, "retries": {"transient": 1, "outage": 1, "fatal": 1},
        "shell_writes_denied": 2, "shell_trap_recoveries": 1,
        "background_killed": 1})])
    line = lines[0]
    assert line.startswith("- worker.md 1.0s ($0.5000): ")
    for said in ("retried after transient 1", "limit events 1",
                 "refused calls 1", "shell writes refused 2",
                 "shell-trap recoveries 1", "leftover processes ended 1"):
        assert said in line, said


def test_a_new_test_carries_the_spec_line_a_step_tied_it_to():
    block = handoff.parse("HANDOFF\nDID:\n- test_rounds_half_up encodes"
                          " TASK.md:12 - halves round up\nEND HANDOFF\n")
    assert summary.spec_for("test_money.py::test_rounds_half_up",
                            [("tester", block)]) == \
        " - encodes TASK.md:12 (tester)"
    assert summary.spec_for("test_money.py::test_other",
                            [("tester", block)]) == ""


def test_a_read_call_and_shell_reads_are_files_and_ranges(tmp_path,
                                                          monkeypatch):
    a_transcript(tmp_path, "s-1", [
        ("Read", {"file_path": str(tmp_path / "w" / "a.py")}),
        ("Read", {"file_path": str(tmp_path / "w" / "b.py"), "offset": 10,
                  "limit": 5}),
        ("Bash", {"command": "cat c.py | grep x; head -n 20 d.py"}),
        ("Bash", {"command": "sed -i 's/a/b/' e.py"})])
    monkeypatch.setattr(handoff, "PROJECTS", tmp_path)
    got = handoff.reads("s-1", root=tmp_path / "w")
    assert got == [("a.py", ""), ("b.py", "10-14"), ("c.py", ""),
                   ("d.py", "1-20")]
    assert handoff.reads("s-none") is None
    kept = tmp_path / "D--a-place" / "s-1.jsonl"
    text = kept.read_text(encoding="utf-8")
    kept.write_text(text + text.split("\n")[0] + "\n", encoding="utf-8")
    assert handoff.reads("s-1", root=tmp_path / "w") == got


def said_of(tmp_path, monkeypatch, calls, item):
    """-> the read section's `said` lines for a READ line `item` of a pass
    whose session made `calls`, each (tool name, input, what it printed)."""
    folder = tmp_path / "projects" / "D--w"
    folder.mkdir(parents=True)
    lines = []
    for i, (name, given, out) in enumerate(calls):
        lines.append(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t" + str(i), "name": name,
             "input": given}]}}))
        lines.append(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t" + str(i),
             "content": out}]}}))
    (folder / "s-1.jsonl").write_text("\n".join(lines) + "\n",
                                      encoding="utf-8")
    monkeypatch.setattr(handoff, "PROJECTS", tmp_path / "projects")
    block = handoff.parse("HANDOFF\nDID:\n- looked\nREAD:\n- " + item
                          + "\nEND HANDOFF\n")
    p = summary.a_pass("worker.md", "worker", 1.0, block, [], False, "ok", "",
                       facts=summary.facts_of({"session": "s-1"},
                                              str(tmp_path / "w")))
    return [l for l in summary.read_lines([p]) if l.startswith("  said")]


EMPTY = "(Bash completed with no output)"


def bash(command, out="ok"):
    return ("Bash", {"command": command}, out)


def grep(tmp_path, path, out, mode="content"):
    given = {"pattern": "x", "path": str(tmp_path / "w" / path)}
    if mode:
        given["output_mode"] = mode
    return ("Grep", given, out)


SEARCHED = [
    (lambda t: [bash('cd "' + str(t / "w") + '" && grep -n "def test_\\|'
                     'parametrize" tests/test_delimiter.py',
                     "3:def test_a\n9:@pytest.mark.parametrize")],
     "tests/test_delimiter.py - list of test names and parametrize lines"),
    (lambda t: [bash("python -m pytest -q 2>&1 | tail -2 && grep -n "
                     '"def test" tests/test_report.py | head -20',
                     "1 passed\n6:def test_report")],
     "tests/test_report.py:6-56 - the report lines"),
    (lambda t: [bash('grep -n -A8 -e "def test_any" tests/test_cases.py',
                     "20:def test_any")],
     "tests/test_cases.py:20-24 - the case"),
    (lambda t: [grep(t, "tests/test_export.py", "7:def test_json")],
     'tests/test_export.py:7-14 - the existing JSON test expects "-25.00".'),
    (lambda t: [grep(t, "ledgerlite", "ledgerlite\\budgets.py:12:    if amount <= 0:\n"
                     "ledgerlite\\money.py:25:def pct(part, whole):")],
     "ledgerlite/budgets.py:12-13,32 - the zero check, seen through Grep"),
    (lambda t: [bash('grep -n "def count_option" -A12 logsift/*.py',
                     "logsift/cli.py:10:def count_option(text):\n"
                     "logsift/cli.py-11-    return int(text)")],
     "logsift/cli.py:10-22 - count_option"),
    (lambda t: [bash("git diff 693232e -- logsift/ TASK.md",
                     "diff --git a/TASK.md b/TASK.md\n+one\n"
                     "diff --git a/logsift/cli.py b/logsift/cli.py\n+two\n"
                     "diff --git a/logsift/filters.py b/logsift/filters.py\n"
                     "+three")],
     "logsift/filters.py, logsift/cli.py, TASK.md: the diff since 693232e"),
    (lambda t: [bash("cat tests/conftest.py tests/test_commands.py && "
                     "sed -n 1,70p tests/test_report.py")],
     ("tests/conftest.py, tests/test_commands.py, tests/test_report.py - the"
      " existing cases and the `make` fixture")),
    (lambda t: [("Read", {"file_path": str(t / "w" / "calc.py")}, "1\tx")],
     "calc.py."),
    (lambda t: [("Read", {"file_path": str(t / "w" / "calc.py")}, "1\tx")],
     "`calc.py`, the module"),
    (lambda t: [bash("grep -rn x src; grep -rn y tests",
                     "src/a.py:3:x\ntests/test_a.py:9:y")], "src/a.py - x"),
    (lambda t: [bash("grep x a.py", "x = 1")], "a.py - x"),
    (lambda t: [bash("grep -n x a.py | head -3; false", "Exit code 1\n3:x")],
     "a.py - x"),
    (lambda t: [bash("git diff 25b87c6 -- gradebook TASK.md",
                     "diff --git a/TASK.md b/TASK.md\n+one\n"
                     "diff --git a/gradebook/inputs.py b/gradebook/inputs.py\n"
                     "+two")],
     "git diff 25b87c6 of gradebook/ and TASK.md - the whole code change"),
    (lambda t: [bash("git diff 25b87c6 -- calc.py",
                     "diff --git a/calc.py b/calc.py\n+one")],
     "git diff 25b87c6 -- calc.py - the change"),
    (lambda t: [bash("cat calc.py", "x = 1")], "cat calc.py - the module"),
    (lambda t: [bash("git show HEAD:a/b.py | grep -n x", "4:x")],
     "git HEAD a/b.py (grep) - the x line"),
    (lambda t: [bash('cd "' + str(t / "w") + '" && git show HEAD:pkg/rules'
                     '.py | grep -n "def check\\|opts\\." ; grep -rn "check"'
                     " tests/ | grep -i error | head",
                     "37:def check(opts):\n48:    return found\n"
                     "tests/test_a.py:3:    check error")],
     "git HEAD pkg/rules.py (grep) - check reads its opts in order"),
    (lambda t: [bash("git show HEAD:a.py", "x = 1")],
     "a.py - the module as committed"),
    (lambda t: [bash("git --no-pager show abc123:pkg/a.py | head -40",
                     "x = 1")], "pkg/a.py:1-40 - the top"),
    (lambda t: [bash("git show HEAD:pkg/caf" + chr(0xe9) + ".py | grep -n x",
                     "4:x")], "pkg/caf" + chr(0xe9) + ".py - x"),
    (lambda t: [bash("git show HEAD~1:pkg/b.py | cat | grep -n x", "4:x")],
     "pkg\\b.py - x"),
]


@pytest.mark.parametrize("calls, item", SEARCHED)
def test_a_read_line_is_held_to_the_call_that_printed_or_searched_its_file(
        tmp_path, monkeypatch, calls, item):
    assert said_of(tmp_path, monkeypatch, calls(tmp_path), item) == [
        "  said: " + item]


NOT_SEARCHED = [
    (lambda t: [bash("grep -n x a.py", "3:x")], "b.py - the other module"),
    (lambda t: [bash('grep -n "a.py" b.py', "3:a.py")], "a.py - x"),
    (lambda t: [bash("grep -c x a.py", "3")], "a.py - x"),
    (lambda t: [bash("grep -nl x a.py", "a.py")], "a.py - x"),
    (lambda t: [bash("grep -q x a.py", "")], "a.py - x"),
    (lambda t: [bash("grep --count x a.py", "3")], "a.py - x"),
    (lambda t: [bash("rg -l x src", "src/a.py")], "src/a.py - x"),
    (lambda t: [bash("grep -n x a.py | wc -l", "3")], "a.py - x"),
    (lambda t: [bash("grep -n x a.py > hits.txt", "")], "a.py - x"),
    (lambda t: [grep(t, "a.py", "a.py", mode=None)], "a.py - x"),
    (lambda t: [grep(t, "pkg", "pkg\\b.py:3:x")], "pkg/a.py - x"),
    (lambda t: [bash("grep see TASK.md", "logsift/parse.py: the parser")],
     "logsift/parse.py - the parser"),
    (lambda t: [bash("git diff 693232e --stat", " logsift/cli.py | 3 +-")],
     "logsift/cli.py - the diff"),
    (lambda t: [bash("git diff -U0 TASK.md | grep -c '^-'",
                     "diff --git a/TASK.md b/TASK.md\n0")], "TASK.md - x"),
    (lambda t: [bash("cat a.py")], "a.py, b.py - both modules"),
    (lambda t: [("Write", {"file_path": str(t / "w" / "t.py"),
                           "content": "x"}, "ok")],
     "t.py:1-170 - the order the new test was placed in"),
    (lambda t: [bash("grep -n zzz a.py", "")], "a.py - x"),
    (lambda t: [bash("grep -n zzz a.py | head -20", EMPTY)], "a.py - x"),
    (lambda t: [bash("grep -n zzz a.py || true", EMPTY)], "a.py - x"),
    (lambda t: [bash("grep zzz a.py | head", EMPTY)], "a.py - x"),
    (lambda t: [bash("grep -n zzz a.py", "Exit code 1")], "a.py - x"),
    (lambda t: [bash("grep -n zzz a.py", "Error: Exit code 1")], "a.py - x"),
    (lambda t: [grep(t, "a.py", "No matches found")], "a.py - x"),
    (lambda t: [grep(t, "a.py", "")], "a.py - x"),
    (lambda t: [bash("python -m pytest -q; grep -rn zzz .",
                     "tests/test_a.py:12: AssertionError\n1 failed")],
     "tests/test_a.py - x"),
    (lambda t: [bash("python -m pytest -q; grep -n zzz tests/test_a.py",
                     "tests/test_a.py:12: AssertionError\n1 failed")],
     "tests/test_a.py - x"),
    (lambda t: [bash("grep -m 0 -n x a.py", "")], "a.py - x"),
    (lambda t: [bash("grep -n --max-count=0 x a.py; echo 3:x", "3:x")],
     "a.py - x"),
    (lambda t: [bash("grep --coun x a.py", "3")], "a.py - x"),
    (lambda t: [bash("grep --files-with x a.py", "a.py")], "a.py - x"),
    (lambda t: [bash("grep -c x b.py; grep -n zzz a.py", "3")], "a.py - x"),
    (lambda t: [bash("grep -n x a.py", "grep: a.py: No such file or"
                     " directory")], "a.py - x"),
    (lambda t: [bash("ls; grep zzz a.py", "a.py\nb.py")], "a.py - x"),
    (lambda t: [bash("git diff 25b87c6 -- TASK.md",
                     "diff --git a/TASK.md b/TASK.md\n+one")],
     "git diff 25b87c6 of gradebook/ and TASK.md - the whole code change"),
    (lambda t: [bash("git diff 25b87c6 -- gradebook",
                     "diff --git a/gradebook/inputs.py b/gradebook/inputs.py\n"
                     "+two")],
     "git diff 25b87c6 of gradebook/ and TASK.md - the whole code change"),
    (lambda t: [bash("git diff 25b87c6 --stat", " calc.py | 3 +-")],
     "git diff 25b87c6 -- calc.py - the change"),
    (lambda t: [bash("git log -3", "abc fix")], "git log -3 - the history"),
    (lambda t: [bash("cat gradebook/inputs.py", "x = 1")],
     "gradebook/ - the package"),
    (lambda t: [bash("git diff -- calc.py", "diff --git a/calc.py b/calc.py")],
     "git - the change"),
    (lambda t: [bash("git show HEAD:a/b.py | grep -c x", "3")],
     "git HEAD a/b.py (grep) - x"),
    (lambda t: [bash("git show HEAD --stat", " a/b.py | 3 +-")],
     "a/b.py - the change"),
    (lambda t: [bash("git show HEAD:a/b.py | grep -n zzz", EMPTY)],
     "a/b.py - x"),
    (lambda t: [bash("git show HEAD:a/b.py", "fatal: path 'a/b.py' does not"
                     " exist in 'HEAD'")], "a/b.py - x"),
    (lambda t: [bash("git show HEAD:a/b.py | grep -n \"x", "4:x")],
     "a/b.py - x"),
    (lambda t: [bash("git show HEAD:a/b.py | wc -l", "50")], "a/b.py - x"),
    (lambda t: [bash("git show HEAD:a/b.py > b.txt", "")], "a/b.py - x"),
    (lambda t: [bash("git show HEAD:a/b.py | grep -n x c.py", "4:x")],
     "a/b.py - x"),
    (lambda t: [bash("git show HEAD:a/b.py | head -5 c.py | grep -n x",
                     "4:x")], "a/b.py - x"),
    (lambda t: [bash("git show HEAD: | grep -n x", "4:x")], "a/b.py - x"),
]


@pytest.mark.parametrize("calls, item", NOT_SEARCHED)
def test_a_read_line_no_call_printed_or_searched_its_file_for_stays_flagged(
        tmp_path, monkeypatch, calls, item):
    assert said_of(tmp_path, monkeypatch, calls(tmp_path), item) == [
        "  said, not in its transcript: " + item]


def test_each_gate_s_command_sits_beside_its_own_result_after_a_runner_check(
        tmp_path):
    class FM(object):
        steps = [{"role": "worker", "prompt": "worker.md", "gates": [
            {"gate": "length", "max": 40},
            {"gate": "command", "command": ["python", "-m", "pytest", "-q"]},
            {"gate": "command", "command": ["ruff", "check"]}]}]

    folder = tmp_path / "run"
    folder.mkdir()
    line = {"seq": 1, "step": "worker.md", "outcome": "gate failed",
            "gates": [{"gate": "quote", "ok": False, "detail": "not there"},
                      {"gate": "length", "ok": True, "detail": "3 lines"},
                      {"gate": "command", "ok": True, "detail": "exit 0"},
                      {"gate": "command", "ok": False, "detail": "exit 1"}]}
    (folder / "steps.jsonl").write_text(json.dumps(line) + "\n",
                                        encoding="utf-8")
    [p] = summary.passes_of(folder, {"worker.md": "worker"}, FM)
    assert [(g["gate"], g["command"]) for g in p["gates"]] == [
        ("quote", ""), ("length", ""), ("command", "python -m pytest -q"),
        ("command", "ruff check")]


FIFTY = "".join("line " + str(n) + "\n" for n in range(1, 51))
NAMED = "pkg/caf" + chr(0xe9) + ".py"


def a_place(tmp_path):
    place = tmp_path / "place"
    (place / "pkg").mkdir(parents=True)
    (place / "pkg" / "lines.py").write_text(FIFTY, encoding="utf-8")
    (place / NAMED).write_bytes(b"a\r\nb\r\nc")
    (place / "pkg" / "empty.py").write_text("", encoding="utf-8")
    return place


def past_of(said, place, changed=None):
    block = handoff.parse("HANDOFF\n" + said + "\nEND HANDOFF\n")
    return [(f["cite"], f["lines"], f["changed"])
            for f in summary.past_end(block, place, changed)]


def test_a_cite_past_a_file_s_last_line_is_found_with_the_file_s_length(
        tmp_path):
    place = a_place(tmp_path)
    said = ("DID:\n- pkg/lines.py:98: cause 1, also `pkg/lines.py:40-60`\n"
            "- pkg/lines.py:50 - the last line, and pkg/lines.py:1-50\n"
            "READ:\n- pkg\\lines.py:51 - one past it\n"
            "- " + NAMED + ":3 - its last line, with no line break after it\n"
            "- " + NAMED + ":4 - past it\n"
            "- pkg/empty.py:1 - an empty file\n"
            "- pkg/gone.py:9 - not in the place\n"
            "- " + str(place / "pkg" / "lines.py") + ":70 - by its path\n"
            "BECAUSE:\n- it splits there\n  from: pkg/lines.py:99\n"
            "  led to: nothing\n")
    assert past_of(said, place) == [
        ("pkg/lines.py:98", 50, None), ("pkg/lines.py:40-60", 50, None),
        ("pkg/lines.py:99", 50, None), ("pkg/lines.py:51", 50, None),
        (NAMED + ":4", 3, None), ("pkg/empty.py:1", 0, None),
        ("pkg/lines.py:70", 50, None)]


def test_a_command_or_output_a_step_quotes_or_a_file_elsewhere_is_no_cite(
        tmp_path):
    place = a_place(tmp_path)
    (tmp_path / "out.py").write_text("x\n", encoding="utf-8")
    said = ("VERIFIED:\n- the code splits lines\n"
            "  cmd: grep -n x pkg/lines.py:95\n  saw: pkg/lines.py:97: x\n"
            "DID:\n- ../out.py:7 - outside the place\n"
            "- " + str(tmp_path / "out.py") + ":7 - outside, by its path\n"
            "- python 3.10:5 and 12:30 name no file\n")
    assert past_of(said, place) == []
    for block in (handoff.parse("no block"), handoff.empty(), {},
                  handoff.parse("HANDOFF\nDID:\nEND HANDOFF\n")):
        assert summary.past_end(block, place) == []
    assert summary.past_end(handoff.parse(
        "HANDOFF\nDID:\n- pkg/lines.py:98\nEND HANDOFF\n"), None) == []


def test_a_cite_past_the_end_says_whether_the_step_changed_the_file(tmp_path):
    place = a_place(tmp_path)
    seen = []

    def told(want):
        def changed(rel, data):
            seen.append((rel, len(data)))
            return want
        return changed

    for want in (False, True, None):
        assert past_of("DID:\n- pkg/lines.py:98\n", place, told(want)) == [
            ("pkg/lines.py:98", 50, want)]
    assert seen[0] == ("pkg/lines.py",
                       len((place / "pkg" / "lines.py").read_bytes()))


def test_whether_the_step_changed_a_cited_file_comes_from_its_snapshot_or_git(
        tmp_path):
    from types import SimpleNamespace

    from agentweft.guardrails import snapshot

    place = a_repo(tmp_path / "repo")
    was = (place / "calc.py").read_bytes()
    run = SimpleNamespace(workdir=place, start=None, looked=None,
                          tree=summary.tree(place))
    changed = engine.Run.changed_in_step
    assert changed(run, "calc.py", was) is False
    lf = was.replace(b"\r\n", b"\n")
    assert changed(run, "calc.py", lf) is False
    assert changed(run, "calc.py", lf.replace(b"\n", b"\r\n")) is False
    assert changed(run, "calc.py", b"x\n") is None
    (place / "new.py").write_text("x\n", encoding="utf-8")
    assert changed(run, "new.py", b"x\n") is None
    run.start = SimpleNamespace(root=place)
    run.looked = ({}, {}, {"calc.py": snapshot._sha(b"x\n")})
    assert changed(run, "calc.py", b"x\n") is False
    assert changed(run, "calc.py", was) is True
    assert changed(run, "new.py", b"x\n") is None
    elsewhere = tmp_path / "loose"
    elsewhere.mkdir()
    assert changed(SimpleNamespace(workdir=elsewhere, start=None,
                                   looked=None,
                                   tree=summary.tree(elsewhere)),
                   "calc.py", was) is None


def test_the_read_section_flags_a_cite_past_a_file_s_end_on_its_step():
    p = summary.a_pass("worker.md", "worker", 1.0, handoff.parse(WORKER), [],
                       False, "ok", "", facts={"read": None, "past_end": [
                           {"cite": "pkg/lines.py:98", "lines": 50,
                            "changed": False},
                           {"cite": "pkg/a.py:95", "lines": 80,
                            "changed": True},
                           {"cite": "pkg/b.py:9", "lines": 3,
                            "changed": None}]})
    assert summary.read_lines([p])[-1] == (
        "  cites past a file's last line: pkg/lines.py:98 (50 lines);"
        " pkg/a.py:95 (80 lines after this step, which changed the file);"
        " pkg/b.py:9 (3 lines after this step, which may have changed the"
        " file)")
    alone = summary.a_pass("worker.md", "worker", 1.0, handoff.empty(), [],
                           False, "ok", "", facts={"read": None, "past_end": [
                               {"cite": "pkg/lines.py:98", "lines": 50,
                                "changed": False}]})
    assert summary.read_lines([alone]) == [
        "- worker.md: no transcript to read it from",
        "  cites past a file's last line: pkg/lines.py:98 (50 lines)"]


def test_a_cite_past_a_file_s_end_is_flagged_on_its_step_as_the_file_stood(
        tmp_path, monkeypatch, fake_cli):
    from test_stops import steps_of

    place = a_repo(tmp_path / "repo")
    (place / "pkg").mkdir()
    (place / "pkg" / "lines.py").write_text(FIFTY, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "more")
    monkeypatch.setattr(handoff, "PROJECTS", tmp_path / "projects")
    a_flow(tmp_path, monkeypatch, "two", ["worker", "patcher"],
           tail="workdir: " + place.as_posix() + "\n" + CLAUDE)
    cited = ("done\n\nHANDOFF\nDID:\n- pkg/lines.py:98: splits on every"
             " line break\nEND HANDOFF\n")
    fake_cli(answer(cited.replace("\nEND", "\n- pkg/new.py:5 - to be made"
                                  "\nEND"), session="w-1"),
             answer(cited.replace("done", "fixed"), session="p-1"))
    real = engine.Run.step

    def step(self, name, *a, **kw):
        if name == "patcher.md":
            (place / "pkg" / "lines.py").write_text(FIFTY * 3,
                                                     encoding="utf-8")
            (place / "pkg" / "new.py").write_text("a\nb\nc\n",
                                                  encoding="utf-8")
        return real(self, name, *a, **kw)

    monkeypatch.setattr(engine.Run, "step", step)
    assert engine.main() == 0
    folder = the_folder()
    read = section((folder / summary.FILE).read_text(encoding="utf-8"),
                   "read")
    assert read.split("\n")[:2] == [
        "- worker.md: no transcript to read it from",
        "  cites past a file's last line: pkg/lines.py:98 (50 lines)"], read
    assert read.count("cites past") == 1
    assert [(s["step"], s.get("past_end")) for s in steps_of(folder)][:2] == [
        ("worker.md", [{"cite": "pkg/lines.py:98", "lines": 50,
                        "changed": False}]), ("patcher.md", None)]


ASKS = "NEEDS: which file?\nOPTIONS:\n- a.py\n- b.py\n"
CONFLICTS = ('CONFLICT: RULES.md:3 "every line of the output names its source'
             ' file"\nrequest: a summary with no file names in it\n')


def a_stop(tmp_path, monkeypatch, fake_cli, said, cite, change=False):
    """-> (cause, past_end) of the one step line of a run whose worker
    answers `said` with a block that reads `cite`, and stops there."""
    from test_stops import steps_of

    place = a_repo(tmp_path / "repo")
    (place / "pkg").mkdir()
    (place / "pkg" / "lines.py").write_text(FIFTY, encoding="utf-8")
    (place / NAMED).write_bytes(b"a\r\nb\r\nc")
    (place / "RULES.md").write_text(
        "# rules\n\nevery line of the output names its source file\n",
        encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "more")
    monkeypatch.setattr(handoff, "PROJECTS", tmp_path / "projects")
    a_flow(tmp_path, monkeypatch, "stops", ["worker", "reviewer"],
           tail="lead: none\nworkdir: " + place.as_posix() + "\n" + CLAUDE)
    fake_cli(answer(said + "\nHANDOFF\nDID:\n- read the module\nREAD:\n- "
                    + cite + " - the whole module\nEND HANDOFF\n",
                    session="w-1"))
    if change:
        real = engine.Run.step

        def step(self, name, *a, **kw):
            (place / "pkg" / "more.py").write_text("x = 1\n", encoding="utf-8")
            return real(self, name, *a, **kw)

        monkeypatch.setattr(engine.Run, "step", step)
    assert engine.main() == 2
    [line] = steps_of(the_folder())
    return line["cause"], line.get("past_end")


@pytest.mark.parametrize("said, cite, change, cause", [
    (ASKS, "pkg/lines.py:1-51", False, stops.WAITING),
    (ASKS, "pkg\\lines.py:51", False, stops.WAITING),
    (ASKS, "pkg/lines.py:1-51", True, stops.WAITING),
    (CONFLICTS, "pkg/lines.py:1-51", False, (stops.CONFLICT,))],
    ids=["asked", "asked-backslash", "worked-then-asked", "conflict"])
def test_a_cite_past_the_end_is_flagged_on_a_step_stopped_before_its_gates(
        said, cite, change, cause, tmp_path, monkeypatch, fake_cli):
    stopped, past = a_stop(tmp_path, monkeypatch, fake_cli, said, cite, change)
    assert stopped in cause
    assert past == [{"cite": cite.replace("\\", "/"), "lines": 50,
                     "changed": False}]


@pytest.mark.parametrize("cite, want", [
    ("pkg/lines.py:1-51", [{"cite": "pkg/lines.py:1-51", "lines": 50,
                            "changed": False}]),
    ("pkg/lines.py:1-50", None)], ids=["past", "inside"])
def test_a_scored_run_flags_a_cite_past_the_end_on_a_step_that_asked(
        cite, want, tmp_path, monkeypatch):
    from agentweft.runner import once
    from test_stops import steps_of

    place = a_repo(tmp_path / "repo")
    (place / "pkg").mkdir()
    (place / "pkg" / "lines.py").write_text(FIFTY, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "more")
    a_flow(tmp_path, monkeypatch, "asks", ["worker", "reviewer"],
           tail="lead: none\n")
    trail = tmp_path / "trail"
    trail.mkdir()
    once.run_once("asks", provider={"provider": "fake", "replies": {
        "worker.md": [ASKS + "\nHANDOFF\nREAD:\n- " + cite
                      + " - the whole module\nEND HANDOFF\n"]}},
        trail=trail, workdir=str(place))
    [line] = steps_of(trail)
    assert line["cause"] in stops.WAITING
    assert line.get("past_end") == want


@pytest.mark.parametrize("said, cite", [
    (ASKS, "pkg/lines.py:1-50"), (ASKS, NAMED + ":3"),
    (CONFLICTS, "pkg/lines.py:50")], ids=["asked", "no-break", "conflict"])
def test_an_in_range_cite_on_a_step_that_stops_before_its_gates_is_no_flag(
        said, cite, tmp_path, monkeypatch, fake_cli):
    assert a_stop(tmp_path, monkeypatch, fake_cli, said, cite)[1] is None
