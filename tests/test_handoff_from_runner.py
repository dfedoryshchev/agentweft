"""the handoff's changed, read, tests and retro sections are written by the
runner from git, the step transcripts and steps.jsonl, never from a step's
text."""
import json
import subprocess
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, handoff, summary
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
    [line] = lines
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
