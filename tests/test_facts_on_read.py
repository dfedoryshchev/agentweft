"""a claude step is handed a file's facts the first time it opens the file,
through a PostToolUse hook the runner passes in its own --settings: the hook
answers with the facts as the call's additionalContext, once a file a
session, never a fact the brief handed, never a project-wide one, and logs
the ids it handed, which go on the step's line as facts_attached."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.guardrails import factsread
from agentweft.providers import cli_provider
from agentweft.runner import engine
from conftest import FakeCli
from test_facts_attached import CODE, a_place, a_run, entry, put
from test_stops import answer, steps_of, the_folder

NL = chr(10)


def an_index(tmp_path):
    a_place(tmp_path)
    put(tmp_path, "facts/pkg/cli.py.md",
        entry("F-0003", "pkg/cli.py", "main hands argv[0] to parse",
              "the cli reads one argument"))
    put(tmp_path, "facts/_project.md",
        entry("F-0004", ".", "every module is plain python",
              "no build step"))
    index = {"facts": [
        {"id": "F-0002", "scopes": ["pkg/"], "live": True,
         "important": False, "project_wide": False,
         "text": "- F-0002 pkg/ (convention): every module under pkg/ raises"},
        {"id": "F-0003", "scopes": ["pkg/cli.py"], "live": True,
         "important": False, "project_wide": False,
         "text": "- F-0003 pkg/cli.py (convention): main hands argv[0]"},
        {"id": "F-0004", "scopes": ["."], "live": True, "important": False,
         "project_wide": True,
         "text": "- F-0004 . (convention): every module is plain python"}]}
    path = tmp_path / "run" / factsread.INDEX
    path.parent.mkdir()
    path.write_text(json.dumps(index), encoding="utf-8")
    return path, tmp_path / "run" / factsread.FILE


def call(tmp_path, rel, tool="Read", session="s-1"):
    given = {"path": str(tmp_path / rel)} if tool == "Grep" \
        else {"file_path": str(tmp_path / rel)}
    return json.dumps({"hook_event_name": "PostToolUse", "tool_name": tool,
                       "tool_input": given, "tool_response": {},
                       "session_id": session, "cwd": str(tmp_path)})


def said(tmp_path, index, log, raw, handed=()):
    argv = [str(tmp_path), str(index), str(log)]
    if handed:
        argv = argv + [factsread.HANDED, ",".join(handed)]
    out = factsread.decide(argv, raw)
    return json.loads(out)["hookSpecificOutput"] if out else None


def test_a_file_opened_gets_its_facts_nearest_first_as_context(tmp_path):
    index, log = an_index(tmp_path)
    got = said(tmp_path, index, log, call(tmp_path, "pkg/cli.py"))
    assert got["hookEventName"] == "PostToolUse"
    text = got["additionalContext"]
    assert "pkg/cli.py" in text.split(NL)[0]
    assert text.index("F-0003") < text.index("F-0002")
    assert "F-0004" not in text
    [line] = [json.loads(l) for l in log.read_text(encoding="utf-8")
              .split(NL) if l.strip()]
    assert (line["session"], line["path"], line["facts"]) == (
        "s-1", "pkg/cli.py", ["F-0003", "F-0002"])
    assert factsread.attached(log.parent, {"s-1"}) == ["F-0003", "F-0002"]
    assert factsread.attached(log.parent, {"s-2"}) == []


def test_a_file_is_looked_up_once_a_session_and_a_fact_is_handed_once(
        tmp_path):
    index, log = an_index(tmp_path)
    assert said(tmp_path, index, log, call(tmp_path, "pkg/cli.py"))
    assert said(tmp_path, index, log, call(tmp_path, "pkg/cli.py",
                                           tool="Edit")) is None
    assert said(tmp_path, index, log, call(tmp_path, "pkg/parse.py")) is None
    again = said(tmp_path, index, log, call(tmp_path, "pkg/cli.py",
                                            session="s-2"))
    assert "F-0003" in again["additionalContext"]


def test_a_fact_the_brief_handed_is_not_handed_again(tmp_path):
    index, log = an_index(tmp_path)
    got = said(tmp_path, index, log, call(tmp_path, "pkg/cli.py"),
               handed=["F-0002"])
    assert "F-0002" not in got["additionalContext"]
    assert "F-0003" in got["additionalContext"]


def test_nothing_is_handed_for_a_folder_another_tool_or_a_file_outside(
        tmp_path):
    index, log = an_index(tmp_path)
    assert said(tmp_path, index, log, call(tmp_path, "pkg", tool="Grep")) \
        is None
    assert said(tmp_path, index, log, call(tmp_path, "pkg/cli.py",
                                           tool="Bash")) is None
    outside = tmp_path.parent / (tmp_path.name + "-other.py")
    outside.write_text("x" + NL, encoding="utf-8")
    raw = json.dumps({"tool_name": "Read", "session_id": "s-1",
                      "tool_input": {"file_path": str(outside)}})
    assert said(tmp_path, index, log, raw) is None
    assert said(tmp_path, index, log, call(tmp_path, "pkg/cli.py",
                                           tool="Grep"))


def test_a_call_the_hook_cannot_read_hands_nothing_and_stops_nothing(
        tmp_path):
    index, log = an_index(tmp_path)
    done = subprocess.run(
        [sys.executable, "-I", factsread.__file__, str(tmp_path), str(index),
         str(log)], input=b"not json", capture_output=True, timeout=60)
    assert (done.returncode, done.stdout) == (0, b"")
    done = subprocess.run(
        [sys.executable, "-I", factsread.__file__, str(tmp_path), str(index),
         str(log)], input=call(tmp_path, "pkg/cli.py").encode("utf-8"),
        capture_output=True, timeout=60)
    assert done.returncode == 0
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert "F-0003" in out["additionalContext"]


def settings_of(argv):
    return json.loads(argv[argv.index("--settings") + 1])


def test_the_hook_goes_out_in_the_settings_only_for_a_go_of_a_step(
        tmp_path):
    p = cli_provider.CliProvider(command="claude")
    p.grant, p.where = ["read", "grep", "shell"], str(tmp_path)
    p.denials = tmp_path / "denials.jsonl"
    p.facts_read = {"place": str(tmp_path), "index": "i.json",
                    "log": "l.jsonl"}
    assert "PostToolUse" not in settings_of(p.argv("x")[0]).get("hooks", {})
    p.facts_handed = ["F-0001", "F-0002"]
    hooks = settings_of(p.argv("x")[0])["hooks"]
    assert "PreToolUse" in hooks
    [post] = hooks["PostToolUse"]
    assert post["matcher"] == "Read|Edit|Grep"
    [hook] = post["hooks"]
    assert hook["args"][:2] == ["-I", Path(factsread.__file__).as_posix()]
    assert hook["args"][2:] == [str(tmp_path), "i.json", "l.jsonl",
                                factsread.HANDED, "F-0001,F-0002"]
    assert "PostToolUse" not in settings_of(
        p.argv("x", tools_used=False)[0])["hooks"]


class Hooked(FakeCli):
    """runs the PostToolUse hook a call's --settings carries, as the cli
    would after a Read of `opened`, before it answers."""

    def __init__(self, place, opened, *answers):
        FakeCli.__init__(self, *answers)
        self.place, self.opened, self.context = place, opened, []

    def run(self, argv, **kw):
        if "-p" in argv and "--settings" in argv:
            post = settings_of(argv).get("hooks", {}).get("PostToolUse")
            if post:
                hook = post[0]["hooks"][0]
                done = subprocess.run(
                    [hook["command"]] + hook["args"],
                    input=call(self.place, self.opened).encode("utf-8"),
                    capture_output=True, timeout=60)
                self.context.append(done.stdout.decode("utf-8"))
        return FakeCli.run(self, argv, **kw)


def hooked(place, monkeypatch, opened):
    return lambda *answers: Hooked(place, opened, *answers).install(
        monkeypatch)


def test_a_step_that_opens_a_file_nobody_named_gets_its_facts_and_its_line_says(
        tmp_path, monkeypatch):
    an_index(tmp_path)
    fake = a_run(tmp_path, monkeypatch, hooked(tmp_path, monkeypatch,
                                               "pkg/cli.py"),
                 ["planner"], answer("done" + NL),
                 task="make pkg/parse.py stricter")
    assert engine.main() == 0
    [context] = fake.context
    text = json.loads(context)["hookSpecificOutput"]["additionalContext"]
    assert "F-0003" in text and "main hands argv[0] to parse" in text
    assert "F-0002" not in text
    [line] = steps_of(the_folder())
    assert line["facts_attached"][-1] == "F-0003"
    assert "F-0002" in line["facts_attached"]
    index = json.loads((the_folder() / factsread.INDEX).read_text(
        encoding="utf-8"))
    by_id = dict((e["id"], e) for e in index["facts"])
    assert by_id["F-0004"]["project_wide"] is True
    assert not any(str(tmp_path) in e["text"] for e in index["facts"])


def test_a_place_with_no_facts_sends_no_hook(tmp_path, monkeypatch):
    put(tmp_path, "pkg/parse.py", CODE)
    fake = a_run(tmp_path, monkeypatch, hooked(tmp_path, monkeypatch,
                                               "pkg/parse.py"),
                 ["planner"], answer("done" + NL),
                 task="make pkg/parse.py stricter")
    assert engine.main() == 0
    assert fake.context == []
    assert not (the_folder() / factsread.INDEX).exists()
