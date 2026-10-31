"""a step is handed a file's facts the first time it opens the file.

the brief hands a step the facts of the files named before its prompt is
written: the task's, the spec's, the ones the steps before it named. a file
nobody named, opened halfway through the step, came with nothing. so `claude`
is handed this module as a PostToolUse hook on Read, Edit and Grep
(`providers/cli_provider.py`), in the run's own `--settings`. after such a
call on one file of the place, the hook looks the file up in the index of the
place's facts the runner wrote when the run's folder was made (`INDEX`), and
returns the ones that hold for it, nearest first, as the call's
`additionalContext`, which the cli hands the model with the call's result.
each file is looked up once a session; a fact the brief handed, or one handed
on an earlier file of the session, is not handed again, and a project-wide
fact is the brief's alone. every lookup is one json line in the run's
`FILE`: the session, the file, the ids handed. the runner reads the lines of
a step's sessions into its line's `facts_attached`.

a call the hook cannot read, or an error of its own, hands nothing and stops
nothing: the hook adds what a step reads, it checks nothing.

the module runs as a script, by path, in a process of its own, so nothing at
its top level may import from the package; the scope rules are read from
`orchestrate/facts.py` by its path, and that module imports only the standard
library.
"""
import datetime
import importlib.util
import json
import os
import sys
from pathlib import Path

INDEX = "facts-index.json"
FILE = "facts-read.jsonl"
TOOLS = ("Read", "Edit", "Grep")
HANDED = "--handed"
# about 400 tokens a file: the step has the file itself open already
CAP = 1500
HEAD = ("facts kept by the runner across runs for {path}, the file you just"
        " opened, that your brief did not hand you:")


def arguments(argv):
    """-> (the place, the index, the log, [the ids the brief handed])."""
    out, handed = [], []
    i = 0
    while i < len(argv):
        if argv[i] == HANDED and i + 1 < len(argv):
            handed.extend(x for x in argv[i + 1].split(",") if x)
            i = i + 2
            continue
        out.append(argv[i])
        i = i + 1
    out = out + [""] * (3 - len(out))
    return out[0], out[1], out[2], handed


def scope_rules():
    path = Path(__file__).resolve().parents[1] / "orchestrate" / "facts.py"
    spec = importlib.util.spec_from_file_location("_scope_rules", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target(data, place):
    """-> the path from the place of the one file the call opened, "" for a
    call on a folder, on no file, or outside the place."""
    given = data.get("tool_input") or {}
    raw = given.get("path") if data.get("tool_name") == "Grep" \
        else given.get("file_path") or given.get("notebook_path")
    if not isinstance(raw, str) or not raw:
        return ""
    cwd = data.get("cwd") or os.getcwd()
    full = Path(os.path.realpath(os.path.join(cwd, raw)))
    if not full.is_file():
        return ""
    try:
        return full.relative_to(Path(os.path.realpath(place))).as_posix()
    except ValueError:
        return ""


def seen(log, session):
    """-> (the files looked up in `session`, the ids handed in it)."""
    files, ids = set(), set()
    try:
        raw = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return files, ids
    for line in raw.split("\n"):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("session") == session:
            files.add(data.get("path"))
            ids.update(data.get("facts") or [])
    return files, ids


def picked(index, rel, skip, rules):
    """-> the index's entries that hold for `rel` and are not in `skip`:
    live before stale, nearest first, `important` first within one rank,
    under CAP characters."""
    found = []
    for entry in index.get("facts") or []:
        if entry.get("id") in skip or entry.get("project_wide"):
            continue
        ranks = [r for r in (rules.rank(s, rel)
                             for s in entry.get("scopes") or [])
                 if r is not None]
        if ranks:
            found.append(((not entry.get("live"), min(ranks),
                           not entry.get("important")), entry))
    found.sort(key=lambda p: p[0])
    out, used = [], 0
    for _, entry in found:
        size = len(entry.get("text") or "") + 1
        if used + size > CAP:
            continue
        out.append(entry)
        used = used + size
    return out


def note(log, session, rel, tool, ids):
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.datetime.now().isoformat(
            timespec="seconds"), "session": session, "path": rel,
            "tool": tool, "facts": ids}) + "\n")


def decide(argv, raw):
    """-> what to print on stdout for one PostToolUse call, "" for
    nothing."""
    place, index_path, log, handed = arguments(argv)
    data = json.loads(raw)
    tool = data.get("tool_name")
    if tool not in TOOLS or not (place and index_path and log):
        return ""
    rel = target(data, place)
    if not rel:
        return ""
    session = data.get("session_id") or ""
    files, ids = seen(log, session)
    if rel in files:
        return ""
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    entries = picked(index, rel, set(handed) | ids, scope_rules())
    note(log, session, rel, tool, [e["id"] for e in entries])
    if not entries:
        return ""
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join([HEAD.format(path=rel)]
                                       + [e["text"] for e in entries])}})


def attached(folder, sessions):
    """-> the ids the hook handed in these sessions, in the order handed,
    from the run folder's log."""
    path = Path(folder) / FILE
    out = []
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("session") in sessions:
            out.extend(i for i in data.get("facts") or [] if i not in out)
    return out


def main():
    try:
        said = decide(sys.argv[1:], sys.stdin.buffer.read().decode(
            "utf-8", errors="replace"))
    except Exception:
        said = ""
    if said:
        sys.stdout.write(said + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
