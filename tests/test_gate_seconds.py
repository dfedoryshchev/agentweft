"""gate time has seconds of its own: each gate a step ran is a line of
gates.jsonl with the gate, the step and its seconds, and the retro puts the
run's wall beside the steps, the gates and the runner's own time, which is
what is left over."""
import json
import re
import sys
import time

sys.path.insert(0, ".")
from agentweft.runner import stops, summary, trace

import test_lead

WALL = re.compile(r"^- wall (\d+(?:\.\d+)?)s: steps (\d+(?:\.\d+)?)s, gates"
                  r" (\d+(?:\.\d+)?)s, runner (\d+(?:\.\d+)?)s$")


def test_each_gate_a_step_ran_has_a_line_with_its_seconds(tmp_path,
                                                         monkeypatch):
    _, _, code, folder, _ = test_lead.build(tmp_path, monkeypatch,
                                            [test_lead.DECIDED])
    assert code == stops.EXIT_OK
    steps = dict((l["seq"], l) for l in (
        json.loads(t) for t in (folder / trace.FILE).read_text(
            encoding="utf-8").split("\n") if t.strip()))
    gates = [json.loads(t) for t in (folder / trace.GATES).read_text(
        encoding="utf-8").split("\n") if t.strip()]
    assert [(g["step"], g["gate"]) for g in gates
            if g["gate"] in ("red-test", "command", "red-first")] == [
        ("tester.md", "red-test"), ("worker.md", "command"),
        ("worker.md", "red-first")]
    for g in gates:
        assert steps[g["seq"]]["step"] == g["step"]
        assert g["seconds"] >= 0
    assert sum(g["seconds"] for g in gates if g["gate"] == "command") > 0


def test_steps_gates_and_runner_add_up_to_the_wall(tmp_path, monkeypatch):
    began = time.time()
    _, _, code, folder, _ = test_lead.build(tmp_path, monkeypatch,
                                            [test_lead.DECIDED])
    took = time.time() - began
    assert code == stops.EXIT_OK
    said = (folder / "handoff.md").read_text(encoding="utf-8").split("\n")
    [found] = [WALL.match(l) for l in said if WALL.match(l)]
    wall, steps, gates, runner = (float(n) for n in found.groups())
    assert abs(steps + gates + runner - wall) < 1
    assert wall <= took + 1
    assert gates > 0
    timed = [json.loads(t)["seconds"] for t in (folder / trace.GATES)
             .read_text(encoding="utf-8").split("\n") if t.strip()]
    assert abs(sum(timed) - gates) < 1


def test_fanned_steps_that_sum_past_the_wall_never_give_the_runner_less_than_nothing():
    passes = [{"seconds": 30.0}, {"seconds": 25.0}]
    line = summary.wall(passes, {"wall": 40.0, "gates": 2.0})
    assert line == ("- wall 40.0s: steps 55.0s summed, past the wall because"
                    " fanned tasks ran side by side, gates 2.0s")
    assert "-" not in line[len("- wall"):]
    assert summary.wall(passes, {"wall": 60.0, "gates": 2.0}) == (
        "- wall 60.0s: steps 55.0s, gates 2.0s, runner 3.0s")
    assert summary.wall([{"seconds": 0.1}], {"wall": 0.3, "gates": 0.2}) == (
        "- wall 0.3s: steps 0.1s, gates 0.2s, runner 0.0s")
