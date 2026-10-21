"""a stdio json-rpc server so an agent can read the journal without me pasting it.

hand rolled. the protocol is a handful of methods over line delimited json on
stdin and stdout, and pulling in a dependency to write forty lines of dict
handling is how i ended up with pydantic and jinja in here twice.
"""
import os
import subprocess
import sys
import tempfile

from agentweft.guardrails import police
from agentweft.runner import state, stops

from . import transport

VERSION = "2024-11-05"
NAME = "flows"

# an agent that can start anything can start repo-audit in a loop, and that one
# has a twenty six call ceiling. so: nothing runs unless it is named here.
ALLOWED = ("weekly-digest", "ops-check", "summarise-and-check")


def resources():
    out = [{"uri": "flows://journal", "name": "run journal",
            "mimeType": "text/markdown"},
           {"uri": "flows://rollup", "name": "last 7 days",
            "mimeType": "text/plain"},
           {"uri": "flows://gates", "name": "gate results, most recent runs",
            "mimeType": "text/markdown"}]
    runs = state.RUNS
    if runs.exists():
        for d in sorted((p for p in runs.iterdir() if p.is_dir()), reverse=True)[:20]:
            out.append({"uri": "flows://run/" + d.name, "name": d.name,
                        "mimeType": "text/markdown"})
    return out


def child(argv, timeout):
    """a python process of this repo's, both ends of its pipe in utf-8: left
    to the platform, each end picks the locale's, which cannot hold every
    character a model or a flow name has."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(argv, capture_output=True, encoding="utf-8",
                          errors="replace", env=env, timeout=timeout)


def marked(text, uri, folders):
    """-> text, wrapped as data when any of the runs it came from was made
    with the off task check on (`guardrails/police.py`)."""
    if any(police.was_on(d) for d in folders):
        return police.untrusted(text, uri)
    return text


def journaled(text):
    """-> the run folders the journal's lines name."""
    out = []
    for line in text.split("\n"):
        said = stops.read(line) if line.strip() else None
        if said is not None and said.run:
            out.append(state.RUNS / said.run)
    return out


def read_resource(uri):
    if uri == "flows://journal":
        p = state.RUNS / "journal.md"
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        return marked(text, uri, journaled(text))
    if uri == "flows://gates":
        runs = state.RUNS
        if not runs.exists():
            return "nothing yet"
        parts = []
        read = []
        for d in sorted((p for p in runs.iterdir() if p.is_dir()), reverse=True)[:10]:
            g = d / "gates.md"
            if g.exists():
                parts.append("# " + d.name + "\n\n" + g.read_text(encoding="utf-8"))
                read.append(d)
        return marked("\n\n".join(parts), uri, read) if parts \
            else "no gates have run yet"
    if uri == "flows://rollup":
        r = child([sys.executable, "rollup.py"], timeout=60)
        return r.stdout or "nothing yet"
    if uri.startswith("flows://run/"):
        d = state.RUNS / uri[len("flows://run/"):]
        if not d.is_dir():
            raise ValueError("no such run: " + uri)
        parts = []
        for f in sorted(p for p in d.rglob("*") if p.is_file()):
            parts.append("## " + f.relative_to(d).as_posix() + "\n\n"
                         + f.read_text(encoding="utf-8"))
        return marked("\n\n".join(parts), uri, [d])
    raise ValueError("no such resource: " + uri)


def tools():
    return [{"name": "run_flow",
             "description": "run one of the flows and return what it produced. "
                            "allowed: " + ", ".join(ALLOWED),
             "inputSchema": {"type": "object",
                             "properties": {
                                 "flow": {"type": "string"},
                                 "task": {"type": "string",
                                          "description": "what the run is "
                                          "for, for a flow that takes one"}},
                             "required": ["flow"]}}]


def policed(name):
    """whether the flow has the off task check on or in shadow, so what its
    run printed goes back marked as data."""
    from agentweft.runner.config import config

    try:
        return police.mode(config(name)) != police.OFF
    except Exception:
        # a flow that will not load is run.py's to refuse, and says so
        return False


def run_flow(name, task=None):
    if name not in ALLOWED:
        return ("not allowed: " + str(name) + ". this server can run: "
                + ", ".join(ALLOWED))
    if task is not None and not isinstance(task, str):
        return "task should be text, not " + type(task).__name__

    argv = [sys.executable, "run.py", name, "--force"]
    held = None
    if task is not None:
        # a file, not --task: argv goes through the platform's encoding and
        # its length limit, and a task is often a pasted report
        fd, held = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "wb") as f:
            f.write(task.encode("utf-8"))
        argv = argv + ["--task-file", held]
    try:
        r = child(argv, timeout=900)
    finally:
        if held:
            os.remove(held)
    out = (r.stdout or "") + (r.stderr or "")
    if policed(name):
        out = police.untrusted(out, "run_flow " + name)
    if r.returncode in EXITS:
        return EXITS[r.returncode] + " (exit " + str(r.returncode) + "):\n\n" + out
    if r.returncode != 0:
        return "the run failed (exit " + str(r.returncode) + "):\n\n" + out
    return out


# what run.py's exit code means. a stop is not always a failure: a park is a
# run waiting for someone, and the client should not read it as broken.
EXITS = {1: "the run could not start",
         2: "the run stopped before the end",
         130: "the run was interrupted"}


def handle(msg):
    method = msg.get("method")
    if method == "initialize":
        # the client sends its own protocolVersion and expects mine back, and
        # a notification with no id afterwards that i must NOT reply to
        return {"protocolVersion": msg.get("params", {}).get("protocolVersion", VERSION),
                "serverInfo": {"name": NAME, "version": "0.1"},
                "capabilities": {"resources": {"subscribe": False}, "tools": {}}}
    if method == "notifications/initialized":
        return None
    if method == "resources/list":
        return {"resources": resources()}
    if method == "tools/list":
        return {"tools": tools()}
    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        if name != "run_flow":
            raise ValueError("unknown tool: " + str(name))
        args = params.get("arguments", {})
        return {"content": [{"type": "text",
                             "text": run_flow(args.get("flow", ""),
                                              args.get("task"))}]}
    if method == "resources/read":
        uri = msg.get("params", {}).get("uri", "")
        return {"contents": [{"uri": uri, "mimeType": "text/markdown",
                              "text": read_resource(uri)}]}
    raise ValueError("unknown method: " + str(method))


def serve(stdin=None, stdout=None):
    return transport.loop(handle, stdin, stdout)
