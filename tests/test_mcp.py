import io
import json
import sys

sys.path.insert(0, ".")
from mcp import server


def rpc(msgs):
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in msgs))
    stdout = io.StringIO()
    server.serve(stdin, stdout)
    return [json.loads(l) for l in stdout.getvalue().split("\n") if l.strip()]


def test_initialize_echoes_the_clients_protocol_version():
    out = rpc([{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"}}])
    assert out[0]["result"]["protocolVersion"] == "2025-06-18"


def test_a_notification_gets_no_reply():
    out = rpc([{"jsonrpc": "2.0", "method": "notifications/initialized"}])
    assert out == []


def test_the_journal_is_listed():
    out = rpc([{"jsonrpc": "2.0", "id": 1, "method": "resources/list"}])
    uris = [r["uri"] for r in out[0]["result"]["resources"]]
    assert "flows://journal" in uris


def test_an_unknown_resource_is_an_error_not_an_empty_read():
    out = rpc([{"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                "params": {"uri": "flows://nope"}}])
    assert "error" in out[0]


def test_an_unknown_method_is_an_error():
    out = rpc([{"jsonrpc": "2.0", "id": 1, "method": "wat"}])
    assert "error" in out[0]
