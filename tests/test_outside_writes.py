"""a write or edit outside the place is refused at the tool, and the step's
line says so."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import police, shellwrite
from agentweft.providers import cli_provider
from agentweft.runner import engine

from test_grant import claude, flag
from test_trace import a_flow, answer, folders, lines

CAFE = "caf" + chr(0xE9)


def edit(path, tool="Write", cwd=None, session="s-1"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    data = {"session_id": session, "hook_event_name": "PreToolUse",
            "tool_name": tool, "tool_input": {key: path, "content": "x\n"}}
    if cwd:
        data["cwd"] = str(cwd)
    return json.dumps(data)


def a_place(tmp_path):
    place = tmp_path / "arm" / "place"
    place.mkdir(parents=True)
    run = tmp_path / "runs" / "r-1"
    run.mkdir(parents=True)
    return place, run / shellwrite.FILE


def decide(denials, place, data):
    return shellwrite.decide([str(denials), shellwrite.PLACE, str(place)],
                             data)


# the hook


def test_a_write_beside_the_place_is_refused_and_noted(tmp_path):
    place, denials = a_place(tmp_path)
    beside = str(tmp_path / "arm" / "helper.py")
    code, said = decide(denials, place, edit(beside, cwd=place))
    assert code == 2
    assert "outside" in said and "helper.py" in said
    [line] = [json.loads(l) for l in denials.read_text("utf-8").splitlines()]
    assert line["session"] == "s-1" and line["tool"] == "Write"
    assert line["outside"] is True and line["path"] == beside


@pytest.mark.parametrize("tail", [
    "../helper.py", "..\\helper.py", "pkg/../../helper.py",
    "../" + CAFE + ".py", "../place2/a.py",
])
def test_a_relative_path_that_climbs_out_is_refused(tmp_path, tail):
    place, denials = a_place(tmp_path)
    code, _ = decide(denials, place, edit(tail, cwd=place))
    assert code == 2, tail


@pytest.mark.parametrize("tool", ["Edit", "MultiEdit", "NotebookEdit"])
def test_every_edit_tool_outside_is_refused(tmp_path, tool):
    place, denials = a_place(tmp_path)
    code, _ = decide(denials, place,
                     edit(str(tmp_path / "x.py"), tool, cwd=place))
    assert code == 2


def test_windows_separators_are_read_as_separators(tmp_path):
    place, denials = a_place(tmp_path)
    out = str(tmp_path / "arm" / "helper.py")
    inside = str(place / "pkg" / "a.py")
    for given in (out.replace("/", "\\"), out.replace("\\", "/")):
        assert decide(denials, place, edit(given, cwd=place))[0] == 2, given
    for given in (inside.replace("/", "\\"), inside.replace("\\", "/")):
        assert decide(denials, place, edit(given, cwd=place)) == (0, ""), \
            given


def test_a_path_with_letters_outside_ascii_is_judged_like_any(tmp_path):
    place = tmp_path / ("pl" + chr(0xE4) + "ce")
    place.mkdir()
    denials = tmp_path / shellwrite.FILE
    inside = str(place / (CAFE + ".py"))
    assert decide(denials, place, edit(inside, cwd=place)) == (0, "")
    code, said = decide(denials, place,
                        edit(str(tmp_path / (CAFE + ".py")), cwd=place))
    assert code == 2 and CAFE in said


@pytest.mark.parametrize("tail", ["a.py", "pkg/a.py", "./pkg/" + CAFE + ".py",
                                  "pkg/../a.py"])
def test_a_write_inside_the_place_passes(tmp_path, tail):
    place, denials = a_place(tmp_path)
    assert decide(denials, place, edit(tail, cwd=place)) == (0, "")
    assert decide(denials, place,
                  edit(str(place / tail), "Edit", cwd=place)) == (0, "")
    assert not denials.exists()


def test_a_write_under_the_runs_own_tmp_passes(tmp_path):
    place, denials = a_place(tmp_path)
    scratch = denials.parent / shellwrite.SCRATCH / "helper.py"
    assert decide(denials, place, edit(str(scratch), cwd=place)) == (0, "")


def test_the_refusal_names_the_runs_tmp_as_where_scratch_goes(tmp_path):
    place, denials = a_place(tmp_path)
    _, said = decide(denials, place,
                     edit(str(tmp_path / "helper.py"), cwd=place))
    assert Path(denials.parent / shellwrite.SCRATCH).as_posix() in said


def test_a_read_outside_the_place_passes(tmp_path):
    place, denials = a_place(tmp_path)
    data = json.dumps({"session_id": "s-1", "tool_name": "Read",
                       "cwd": str(place),
                       "tool_input": {"file_path": str(tmp_path / "x.py")}})
    assert decide(denials, place, data) == (0, "")


def test_a_kept_file_inside_the_place_is_still_refused_as_kept(tmp_path):
    place, denials = a_place(tmp_path)
    kept = place / "decisions.md"
    code, said = shellwrite.decide(
        [str(denials), shellwrite.KEEP, kept.as_posix(), shellwrite.PLACE,
         str(place)], edit(str(kept), cwd=place))
    assert code == 2 and "rulings" in said


def test_the_police_tripwire_still_reads_a_refused_write(tmp_path):
    place = tmp_path / "arm" / "place"
    found = [{"type": "tool_use", "id": "t0", "name": "Write",
              "input": {"file_path": str(tmp_path / "arm" / "helper.py"),
                        "content": "x\n"}},
             {"type": "tool_result", "tool_use_id": "t0", "is_error": True,
              "content": "refused: outside the place"}]
    hits = police.check(found, place=str(place))
    assert [h.tripwire for h in hits] == ["outside"]


# what the cli is handed


def hook_of(argv):
    said = json.loads(flag(argv, "--settings"))
    assert "hooks" in said, "no hook handed to the cli"
    [entry] = said["hooks"]["PreToolUse"]
    [hook] = entry["hooks"]
    return entry["matcher"].split("|"), hook["args"]


def test_a_step_with_no_grant_in_a_place_gets_the_fence(fake_cli, tmp_path):
    cli_ = fake_cli(answer("ok\n"))
    p = claude()
    p.where = tmp_path
    p.ask("x")
    tools, args = hook_of(cli_.calls[0]["argv"])
    for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        assert tool in tools
    at = args.index(shellwrite.PLACE)
    assert Path(args[at + 1]) == tmp_path.resolve()


def test_a_step_granted_write_in_a_place_gets_the_fence(fake_cli, tmp_path):
    cli_ = fake_cli(answer("ok\n"))
    p = claude(grant=["read", "write"])
    p.where = tmp_path
    p.ask("x")
    _, args = hook_of(cli_.calls[0]["argv"])
    assert shellwrite.PLACE in args


def test_a_step_that_only_looks_gets_no_fence(fake_cli, tmp_path):
    cli_ = fake_cli(answer("ok\n"))
    p = claude(grant=["read", "shell"])
    p.where = tmp_path
    p.ask("x")
    tools, args = hook_of(cli_.calls[0]["argv"])
    assert "Write" not in tools and shellwrite.PLACE not in args


# a run


def refusing_outside(monkeypatch, session, path):
    """the cli refuses one write outside the place, as the hook would."""
    real = cli_provider.call

    def call(argv, **kw):
        if "--settings" in argv:
            said = json.loads(flag(argv, "--settings"))
            if "hooks" in said:
                where = said["hooks"]["PreToolUse"][0]["hooks"][0]["args"][2]
                with open(where, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"session": session, "tool": "Write",
                                        "path": path, "outside": True,
                                        "refused": path}) + "\n")
        return real(argv, **kw)

    monkeypatch.setattr(cli_provider, "call", call)


def test_the_steps_why_line_says_the_write_outside_was_refused(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "fenced", ["worker", "reviewer"])
    fake_cli(answer("did it\n", session="s-1"),
             answer("VERDICT: ok\n\nfine\n", session="s-2"))
    refusing_outside(monkeypatch, "s-1", "../helper.py")
    assert engine.main() == 0
    first, second = lines(folders(tmp_path)[0])
    assert first["outcome"] == "ok"
    assert first["why"] == ("the cli refused a write outside the place:"
                            " ../helper.py")
    assert second["why"] is None
