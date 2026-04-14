"""a stdio json-rpc server so an agent can read the journal without me pasting it.

hand rolled. the protocol is a handful of methods over line delimited json on
stdin and stdout, and pulling in a dependency to write forty lines of dict
handling is how i ended up with pydantic and jinja in here twice.
"""
import json
import sys
from pathlib import Path

VERSION = "2024-11-05"
NAME = "flows"

# an agent that can start anything can start repo-audit in a loop, and that one
# has a twenty six call ceiling. so: nothing runs unless it is named here.
ALLOWED = ("weekly-digest", "ops-check", "summarise-and-check")


def _read(stream):
    line = stream.readline()
    if not line:
        return None
    return json.loads(line)


def _write(stream, payload):
    stream.write(json.dumps(payload) + "\n")
    stream.flush()


def resources():
    out = [{"uri": "flows://journal", "name": "run journal",
            "mimeType": "text/markdown"}]
    runs = Path("runs")
    if runs.exists():
        for d in sorted((p for p in runs.iterdir() if p.is_dir()), reverse=True)[:20]:
            out.append({"uri": "flows://run/" + d.name, "name": d.name,
                        "mimeType": "text/markdown"})
    return out


def read_resource(uri):
    if uri == "flows://journal":
        p = Path("runs") / "journal.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""
    if uri.startswith("flows://run/"):
        d = Path("runs") / uri[len("flows://run/"):]
        if not d.is_dir():
            raise ValueError("no such run: " + uri)
        parts = []
        for f in sorted(d.iterdir()):
            parts.append("## " + f.name + "\n\n" + f.read_text(encoding="utf-8"))
        return "\n\n".join(parts)
    raise ValueError("no such resource: " + uri)


def tools():
    return [{"name": "run_flow",
             "description": "run one of the flows and return what it produced. "
                            "allowed: " + ", ".join(ALLOWED),
             "inputSchema": {"type": "object",
                             "properties": {"flow": {"type": "string"}},
                             "required": ["flow"]}}]


def run_flow(name):
    import subprocess

    if name not in ALLOWED:
        return ("not allowed: " + str(name) + ". this server can run: "
                + ", ".join(ALLOWED))

    # this used to hand back whatever run.py had printed by the time the pipe
    # buffer filled, which for the digest is the planner and nothing else. the
    # client saw a plan and called it the answer.
    r = subprocess.run([sys.executable, "run.py", name, "--force"],
                       capture_output=True, text=True, timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return "the run failed:\n\n" + out
    return out


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
        flow = params.get("arguments", {}).get("flow", "")
        return {"content": [{"type": "text", "text": run_flow(flow)}]}
    if method == "resources/read":
        uri = msg.get("params", {}).get("uri", "")
        return {"contents": [{"uri": uri, "mimeType": "text/markdown",
                              "text": read_resource(uri)}]}
    raise ValueError("unknown method: " + str(method))


def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    while True:
        msg = _read(stdin)
        if msg is None:
            return 0
        try:
            result = handle(msg)
            if msg.get("id") is None:
                # a notification. replying to one gets you a protocol error
                # from the client, which took me an evening to work out.
                continue
            _write(stdout, {"jsonrpc": "2.0", "id": msg.get("id"), "result": result})
        except Exception as e:
            _write(stdout, {"jsonrpc": "2.0", "id": msg.get("id"),
                            "error": {"code": -32603, "message": str(e)}})
