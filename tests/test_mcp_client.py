import sys

sys.path.insert(0, ".")
from agentweft.mcp import context
from agentweft.mcp.client import Client

SERVER = """
import json, sys
for line in sys.stdin:
    if not line.strip():
        continue
    m = json.loads(line)
    if m.get("id") is None:
        continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2024-11-05"}
    elif m["method"] == "tools/call":
        r = {"content": [{"type": "text", "text": "a.py 0.91" + chr(10) + "b.py 0.40"}]}
    elif m["method"] == "resources/read":
        r = {"contents": [{"text": "journal here"}]}
    else:
        r = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + chr(10))
    sys.stdout.flush()
"""

FAKE = [sys.executable, "-c", SERVER]


def test_a_tool_call_gets_the_text_back():
    text, err = Client(FAKE).call_tool("hotspots")
    assert err == ""
    assert "a.py 0.91" in text


def test_a_resource_read_gets_the_text_back():
    text, err = Client(FAKE).read_resource("x://y")
    assert err == ""
    assert "journal here" in text


def test_a_missing_server_is_a_detail_not_a_crash():
    text, err = Client(["definitely-not-a-real-binary"]).call_tool("hotspots")
    assert text is None
    assert "PATH" in err


def test_no_server_configured_means_carry_on():
    text, err = context.risk_map({})
    assert text == ""
    assert "no server" in err


def test_the_risk_map_only_becomes_prompt_text_when_there_is_some():
    assert context.as_prompt("") == ""
    assert "risky places" in context.as_prompt("a.py 0.9")
