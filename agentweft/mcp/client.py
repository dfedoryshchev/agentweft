"""talk to somebody else's mcp server.

the server in here lets an agent read my runs. this is the other direction: a
flow reads something a tool knows and i do not. the audit tool i have been
building serves a risk map over stdio, and a worker that is about to touch a
file should probably know whether that file is the one everything depends on.

no dependency. it is the same line delimited json the server speaks, pointed
the other way, and now literally the same module.
"""
import subprocess

from . import transport


class Client(object):
    def __init__(self, command, timeout=60):
        self.command = command
        self.timeout = timeout
        self._id = 0

    def _next_id(self):
        self._id = self._id + 1
        return self._id

    def _session(self, messages):
        """one process, several messages, replies in order. servers are cheap
        to start and holding one open across a whole run is a thing to get
        wrong later, not now."""
        payload = "".join(transport.dumps(m) for m in messages)
        try:
            r = subprocess.run(self.command, input=payload, capture_output=True,
                               text=True, timeout=self.timeout)
        except FileNotFoundError:
            return [{"error": {"message": self.command[0] + " is not on PATH"}}]
        except subprocess.TimeoutExpired:
            return [{"error": {"message": "timed out"}}]
        return transport.parse_lines(r.stdout or "")

    def handshake(self):
        return [{"jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05",
                            "clientInfo": {"name": "agentweft", "version": "0.1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"}]

    def _last(self, replies):
        if not replies:
            return None, "no reply"
        last = replies[-1]
        if "error" in last:
            return None, str(last["error"].get("message", last["error"]))
        return last, ""

    def call_tool(self, name, arguments=None):
        msgs = self.handshake() + [
            {"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/call",
             "params": {"name": name, "arguments": arguments or {}}}]
        last, err = self._last(self._session(msgs))
        if err:
            return None, err
        content = last.get("result", {}).get("content") or []
        return "".join(c.get("text", "") for c in content), ""

    def read_resource(self, uri):
        msgs = self.handshake() + [
            {"jsonrpc": "2.0", "id": self._next_id(), "method": "resources/read",
             "params": {"uri": uri}}]
        last, err = self._last(self._session(msgs))
        if err:
            return None, err
        contents = last.get("result", {}).get("contents") or []
        return "".join(c.get("text", "") for c in contents), ""
