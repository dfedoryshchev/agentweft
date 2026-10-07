"""the risk map is asked for over mcp, with the arguments the tool needs.

a tool server says which arguments a tool requires in `tools/list`. a call
that leaves one out is not refused by every server: one that ranks the files
under `dir` and is handed no `dir` walks nothing and answers with an empty
ranking, which reads exactly like a codebase with no risky files in it.
"""
import os
import sys

import yaml

sys.path.insert(0, ".")
from agentweft.mcp import context
from agentweft.mcp.client import Client
from agentweft.runner import engine, prompts, resume, state

SERVER = """
import json, os, sys
for line in sys.stdin:
    if not line.strip():
        continue
    m = json.loads(line)
    if m.get("id") is None:
        continue
    if m["method"] == "initialize":
        r = {"protocolVersion": "2024-11-05"}
    elif m["method"] == "tools/list":
        r = {"tools": [{"name": "hotspots", "inputSchema": {
            "type": "object", "properties": {"dir": {"type": "string"}},
            "required": ["dir"]}}, {"name": "broken", "inputSchema": {}}]}
    elif m["method"] == "tools/call":
        p = m["params"]
        if p["name"] == "broken":
            r = {"isError": True,
                 "content": [{"type": "text", "text": "it fell over"}]}
        else:
            d = p["arguments"].get("dir", "")
            text = ("a.py  0.910" + chr(10) + "cwd " + os.getcwd() + chr(10)
                    if d else "")
            r = {"content": [{"type": "text", "text": text}]}
    else:
        r = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + chr(10))
    sys.stdout.flush()
"""

FAKE = [sys.executable, "-c", SERVER]


def conf(**more):
    return dict({"command": FAKE, "tool": "hotspots"}, **more)


def test_the_arguments_a_context_block_names_reach_the_tool():
    text, why = context.risk_map(conf(arguments={"dir": "."}))
    assert why == ""
    assert "a.py  0.910" in text


def test_a_required_argument_left_out_is_named_rather_than_an_empty_map():
    text, why = context.risk_map(conf())
    assert text == ""
    assert why == "hotspots needs dir, and the context block does not give it"


def test_an_empty_answer_is_said_rather_than_passed_on_as_no_risk():
    text, why = context.risk_map(conf(arguments={"dir": ""}))
    assert text == ""
    assert why == "hotspots answered with nothing"


def test_a_tool_the_server_does_not_have_is_said():
    text, why = context.risk_map(conf(tool="hotpsots", arguments={"dir": "."}))
    assert text == ""
    assert why == "the server has no tool hotpsots. there is: hotspots, broken"


def test_arguments_that_are_not_a_mapping_are_refused():
    text, why = context.risk_map(conf(arguments=["."]))
    assert text == ""
    assert why == "context: arguments should be a mapping"


def test_a_tool_that_reports_an_error_is_an_error_and_not_a_ranking():
    text, err = Client(FAKE).call_tool("broken")
    assert text is None
    assert err == "it fell over"


def test_the_server_runs_in_the_runs_place(tmp_path):
    text, why = context.risk_map(conf(arguments={"dir": "."}), where=tmp_path)
    assert why == ""
    assert "cwd " + os.path.realpath(str(tmp_path)) in text


def test_the_shipped_flow_names_the_directory_its_tool_requires():
    raw = yaml.safe_load(prompts.flow_path("repo-audit", "flow.yaml")
                         .read_text(encoding="utf-8"))
    assert raw["context"]["tool"] == "hotspots"
    assert raw["context"].get("arguments", {}).get("dir")


def test_the_engine_hands_the_risk_map_the_runs_place(tmp_path, monkeypatch):
    flow = tmp_path / "flows" / "mapped"
    flow.mkdir(parents=True)
    for role in ("planner", "worker"):
        (flow / (role + ".md")).write_text("you are the " + role + ".\n",
                                           encoding="utf-8")
    (flow / "instructions.md").write_text("one step.\n", encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: mapped\n"
        "steps:\n"
        "  - role: planner\n"
        "    prompt: planner.md\n"
        "context:\n"
        "  command: [\"not-a-real-server\"]\n"
        "  arguments: {dir: .}\n"
        "journal: false\n"
        "provider:\n"
        "  provider: fake\n",
        encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    handed = []

    def risk_map(config, where=None):
        handed.append((config.get("arguments"), where))
        return "", "not running"

    monkeypatch.setattr(engine.context, "risk_map", risk_map)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(engine, "CACHE", {})
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "mapped", "--force",
                                      "--workdir", str(work)])
    engine.main()
    assert handed == [({"dir": "."}, work.resolve())]
