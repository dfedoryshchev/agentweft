"""a scored case runs the flow the way a run started by hand does: the same
steps, in the same order, each charged the same, the retro and the preflight
included."""
import sys

sys.path.insert(0, ".")
from agentweft.evals import steps
from agentweft.runner import engine
from test_stops import CLAUDE, a_flow, answer, steps_of, the_folder

GATED = "worker\ngates:\n  - gate: length\n    max_lines: 1"
PARKS = "worker\npreflight:\n  mode: park\n  threshold: 0.7"
NO_MAP = 'context:\n  command: ["not-a-real-server"]\n  tool: hotspots\n'


def both(tmp_path, monkeypatch, fake_cli, name, flow, tail, answers):
    """-> (the lines of a run started by hand, the lines of the same flow
    scored as an eval), each over the same answers."""
    a_flow(tmp_path, monkeypatch, name, flow, tail=tail + CLAUDE)
    fake_cli(*answers)
    engine.main()
    live = steps_of(the_folder())
    fake_cli(*answers)
    trail = tmp_path / "trail"
    trail.mkdir()
    engine.run_once(name, trail=trail)
    return live, steps.read(trail)


def shape(lines):
    return [(steps.said(l), l["cost"], l["won"]) for l in lines]


def test_an_eval_of_a_retro_flow_runs_the_retro(tmp_path, monkeypatch,
                                                fake_cli):
    live, scored = both(tmp_path, monkeypatch, fake_cli, "fails",
                        [GATED, "reviewer"], "retro: true\n",
                        [answer("one\ntwo\n"), answer("one\ntwo\nthree\n"),
                         answer("## seq 1 worker.md\n")])
    assert live[-1]["step"] == "retro.md"
    assert shape(scored) == shape(live)


def test_the_folder_a_cases_lines_go_to_is_not_part_of_a_prompts_hash(
        tmp_path):
    from agentweft.evals import recording

    one, two = tmp_path / "one" / "trail", tmp_path / "two" / "trail"
    said = "every pass in full: {}\n"
    assert recording.digest(said.format(one / "steps.jsonl"), trail=one) == \
        recording.digest(said.format(two / "steps.jsonl"), trail=two)
    assert recording.digest(said.format(one / "steps.jsonl")) != \
        recording.digest(said.format(two / "steps.jsonl"))


def test_an_eval_of_a_flow_with_preflight_holds_the_step_a_run_holds(
        tmp_path, monkeypatch, fake_cli):
    live, scored = both(tmp_path, monkeypatch, fake_cli, "risky",
                        ["planner", PARKS, "reviewer"], NO_MAP,
                        [answer("- edit a.py\n"), answer("done\n"),
                         answer("VERDICT: ok\n\nfine\n")])
    assert [l["outcome"] for l in live] == ["ok", "parked"]
    assert shape(scored) == shape(live)
