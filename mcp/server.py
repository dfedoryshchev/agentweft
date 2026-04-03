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
    return out


def read_resource(uri):
    if uri == "flows://journal":
        p = Path("runs") / "journal.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""
    raise ValueError("no such resource: " + uri)


def handle(msg):
    method = msg.get("method")
    if method == "initialize":
        # the client sends its own protocolVersion and expects mine back, and
        # a notification with no id afterwards that i must NOT reply to
        return {"protocolVersion": msg.get("params", {}).get("protocolVersion", VERSION),
                "serverInfo": {"name": NAME, "version": "0.1"},
                "capabilities": {"resources": {"subscribe": False}}}
    if method == "notifications/initialized":
        return None
    if method == "resources/list":
        return {"resources": resources()}
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
