"""a resume hands the brief the run started on, never the place at resume.

the run digests the place's instruction files when it first starts and hands
a `claude` step their text as it read then. a leg that picks the run up
carries that digest and that text from the run's record: a CLAUDE.md a step
wrote in an earlier leg is not the start state, the guard still refuses a step
that would start its model on it, and the brief stays the first leg's.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.guardrails import briefing
from agentweft.runner import engine

from test_grant import instruction_files
from test_trace import a_flow, answer, folders

NL = chr(10)


def stopped_then_changed(tmp_path, monkeypatch, fake_cli, place_files=True):
    a_flow(tmp_path, monkeypatch, "kept", ["worker"])
    if place_files:
        instruction_files(tmp_path)
    fake_cli(answer("NEEDS: is the suite run with make test?" + NL))
    engine.main()
    [first] = folders(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("written by a step." + NL,
                                        encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run.py", "kept", "--force", "--resume",
                                      first.name, "--answer", "yes, make test"])
    return first


def test_a_resume_keeps_the_start_digest_and_the_guard_still_refuses(
        tmp_path, monkeypatch, fake_cli):
    first = stopped_then_changed(tmp_path, monkeypatch, fake_cli)
    brief = (first / briefing.FOLDER / briefing.FILE).read_text(
        encoding="utf-8")
    later_cli = fake_cli(answer("did it" + NL))
    assert engine.main() != 0
    [later] = [f for f in folders(tmp_path) if f != first]
    assert later_cli.calls == []
    handoff = (later / "handoff.md").read_text(encoding="utf-8")
    assert "CLAUDE.md changed in" in handoff
    assert (later / briefing.FOLDER / briefing.FILE).read_text(
        encoding="utf-8") == brief
    assert "written by a step" not in brief


def test_a_place_that_started_with_no_instruction_file_still_has_none(
        tmp_path, monkeypatch, fake_cli):
    first = stopped_then_changed(tmp_path, monkeypatch, fake_cli,
                                place_files=False)
    later_cli = fake_cli(answer("did it" + NL))
    assert engine.main() != 0
    [later] = [f for f in folders(tmp_path) if f != first]
    assert later_cli.calls == []
    assert not (later / briefing.FOLDER).exists()


def test_a_kept_brief_that_cannot_be_read_hands_nothing_and_holds_the_guard():
    digest, files, why = briefing.carried({"digest": {"CLAUDE.md": 3},
                                           "files": []})
    assert (digest, files) == ({}, []) and "could not be read" in why
    digest, files, why = briefing.carried({"digest": {"a": "b"},
                                           "files": [["CLAUDE.md", 1]]})
    assert (digest, files) == ({}, []) and why
    digest, files, why = briefing.carried({
        "digest": {"CLAUDE.md": "ab"},
        "files": [["CLAUDE.md", "x" + chr(0xE9)], [".claude/rules/a.md",
                                                   None]]})
    assert digest == {"CLAUDE.md": "ab"} and why == ""
    assert files == [("CLAUDE.md", "x" + chr(0xE9)),
                     (".claude/rules/a.md", None)]
    assert briefing.carried(None) == (None, None, "")
