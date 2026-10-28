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


def test_every_gate_on_a_steps_line_has_its_seconds_in_the_gate_log(
        tmp_path, monkeypatch):
    import test_test_edits as te

    place = te.a_place(tmp_path / "repo")
    te.a_flow(tmp_path, "build", te.TESTER + te.WORKER)
    code, _ = te.running(tmp_path, monkeypatch, place,
                         te.writes_of(te.module(te.RIGHT, te.COUNT)), False)
    assert code == 0
    folder = te.folders()[-1]
    steps = [json.loads(t) for t in (folder / trace.FILE).read_text(
        encoding="utf-8").split("\n") if t.strip()]
    timed = [(g["seq"], g["gate"]) for g in (
        json.loads(t) for t in (folder / trace.GATES).read_text(
            encoding="utf-8").split("\n") if t.strip())]
    listed = [(l["seq"], g["gate"]) for l in steps for g in l["gates"]]
    assert (steps[0]["seq"], "test-edits") in listed
    assert [x for x in listed if x not in timed] == []


def test_a_quote_check_is_timed_like_any_gate(tmp_path):
    from agentweft.runner import gating

    (tmp_path / "TASK.md").write_text("amounts are strings\n",
                                      encoding="utf-8")

    class Run(object):
        workdir = str(tmp_path)
        start = None

        def gates_for(self, step):
            return []

    class Out(object):
        output = 'REFUSED: TASK.md:1 "amounts are numbers"\n'
        meta = {}

    class Route(object):
        must = {}

        def gate(self, step, out):
            return ""

    gating.check_step(Run(), Route(), "worker.md", Out())
    gates = Out.meta["gates"]
    assert [r.gate for r in gates] == ["quote"]
    assert gates[0].seconds is not None


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


PHASE = re.compile(r"([a-z]+) (\d+(?:\.\d+)?)s")


def test_the_runner_s_own_seconds_are_named_by_phase_and_add_up_to_the_wall(
        tmp_path, monkeypatch):
    from agentweft.guardrails import snapshot

    real = snapshot.fingerprint

    def slow(*a, **k):
        time.sleep(0.1)
        return real(*a, **k)

    monkeypatch.setattr(snapshot, "fingerprint", slow)
    _, _, code, folder, _ = test_lead.build(tmp_path, monkeypatch,
                                            [test_lead.DECIDED])
    assert code == stops.EXIT_OK
    record = json.loads((folder / "manifest.json").read_text(
        encoding="utf-8"))
    runner = record["runner"]
    phases = runner["phases"]
    assert {"setup", "before", "snapshot", "step", "checks",
            "handoff"} <= set(phases)
    assert abs(runner["steps"] + runner["gates"] + sum(phases.values())
               - runner["wall"]) <= 1
    assert phases["snapshot"] >= 0.5
    said = (folder / "handoff.md").read_text(encoding="utf-8").split("\n")
    [line] = [l for l in said if l.startswith("- runner by phase: ")]
    assert dict((n, float(s)) for n, s in PHASE.findall(line)) == phases
    [found] = [WALL.match(l) for l in said if WALL.match(l)]
    assert abs(float(found.group(4)) - sum(phases.values())) <= 1


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
