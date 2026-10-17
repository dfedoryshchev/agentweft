"""the risk-map example, run the way its readme says: from the top of a clone.

its fake server is a real process the flow's `context:` block starts, so the
ranking reaches preflight over the same json-rpc a warpmap server speaks. the
cold plan goes through; point the planner at the hot plan and the run parks
before the worker, names the file, and says how to carry on.
"""
import pathlib
import shutil
import sys

from agentweft.mcp import context, preflight
from agentweft.runner import engine, prompts, state

HERE = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = HERE / "examples" / "risk-map"
COLD = "examples/risk-map/cold-plan.md"
HOT = "examples/risk-map/hot-plan.md"


def run(monkeypatch, capsys, root, *more):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv", ["run.py", "risk-map", "--force",
                                      "--flows", str(root)] + list(more))
    monkeypatch.chdir(HERE)
    try:
        engine.main()
    except SystemExit:
        pass
    return capsys.readouterr().out


def hot_copy(tmp_path):
    """the shipped flow with the planner pointed at the hot plan, as the
    readme tells a reader to do."""
    root = tmp_path / "flows"
    shutil.copytree(EXAMPLE, root / "risk-map")
    flow = root / "risk-map" / "flow.yaml"
    text = flow.read_text(encoding="utf-8")
    assert COLD in text
    flow.write_text(text.replace(COLD, HOT), encoding="utf-8")
    return root


def the_run():
    [run_dir] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    return run_dir


def resume_line(said):
    lines = said.splitlines()
    at = lines.index("to carry on")
    return lines[at + 1].split()


def test_a_cold_file_goes_through(monkeypatch, capsys):
    said = run(monkeypatch, capsys, HERE / "examples")
    assert "no risk map" not in said
    assert preflight.NO_RANKING not in said
    assert "parked" not in said
    assert "started worker.md" in said
    assert "started reviewer.md" in said
    assert (the_run() / "reviewer.md").exists()


def test_a_hot_file_parks_the_run_and_names_it(tmp_path, monkeypatch, capsys):
    said = run(monkeypatch, capsys, hot_copy(tmp_path))
    assert "no risk map" not in said
    assert "src/store/session.ts" in said
    assert "parked" in said
    assert "started worker.md" not in said
    note = (the_run() / "handoff.md").read_text(encoding="utf-8")
    assert "src/store/session.ts (1.0)" in note
    assert "stopped before worker.md" in note
    said_to = resume_line(said)
    assert said_to[:4] == ["python", "run.py", "risk-map", "--resume"]
    assert said_to[4] == the_run().name


def test_the_resume_command_it_prints_runs_the_worker(tmp_path, monkeypatch,
                                                      capsys):
    root = hot_copy(tmp_path)
    said = run(monkeypatch, capsys, root)
    run_id = resume_line(said)[4]
    said = run(monkeypatch, capsys, root, "--resume", run_id)
    assert "started worker.md" in said
    assert "started reviewer.md" in said
    assert "parked" not in said


def test_the_server_answers_the_way_warpmap_does():
    server = [sys.executable, str(EXAMPLE / "server.py")]
    text, why = context.risk_map({"command": server, "tool": "hotspots",
                                  "arguments": {"dir": "."}}, where=str(HERE))
    assert why == ""
    assert text.splitlines()[0] == "src/store/session.ts  1.000"
    _, why = context.risk_map({"command": server, "tool": "hotspots"},
                              where=str(HERE))
    assert why == "hotspots needs dir, and the context block does not give it"
    _, why = context.risk_map({"command": server, "tool": "hotspots",
                               "arguments": {"dir": "no-such-dir"}},
                              where=str(HERE))
    assert why == "dir: not a directory: no-such-dir"
