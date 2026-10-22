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


def shipped_both(tmp_path, monkeypatch, answers, writes):
    """-> (steps asked by a run of the shipped build-feature flow started by
    hand, steps asked by the same flow scored as an eval), each in a git
    place of its own over the same answers."""
    from agentweft.runner import state
    from test_wrong_test import run_it

    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(state, "RUNS", live / "runs")
    asked, _, code, _, _ = run_it(live, monkeypatch, answers, writes)
    assert code == 0
    there = tmp_path / "eval"
    there.mkdir()
    scored, _, _, _, _ = run_it(there, monkeypatch, answers, writes,
                                scored=True)
    return asked, scored


def test_an_eval_sends_a_named_wrong_implementation_where_a_run_does(
        tmp_path, monkeypatch):
    import test_would_pass as wp

    answers = {"planner.md": [wp.PLAN], "tester.md": [wp.TESTER, wp.TESTER],
               "worker.md": [wp.WORKER], "reviewer.md": [wp.NAMED],
               "reviewer-runs.md": [wp.OK]}
    writes = {"tester.md": [("tests/test_mul.py", wp.RIGHT),
                            ("tests/test_mul.py", wp.MORE)],
              "worker.md": [("calc.py", wp.AFTER)]}
    live, scored = shipped_both(tmp_path, monkeypatch, answers, writes)
    assert live == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                    "tester.md", "reviewer-runs.md", "retro.md"]
    assert scored == live


def test_an_eval_leaves_out_the_reviewer_a_run_leaves_out_on_a_small_change(
        tmp_path, monkeypatch):
    import shutil

    import test_wrong_test as wt

    flows = tmp_path / "flows"
    shutil.copytree(str(wt.FLOWS), str(flows))
    yml = flows / "build-feature" / "flow.yaml"
    yml.write_text(yml.read_text(encoding="utf-8").replace(
        "small_reviewers: 2", "small_reviewers: 1"), encoding="utf-8")
    monkeypatch.setattr(wt, "FLOWS", flows)
    answers = {"planner.md": [wt.PLAN], "tester.md": [wt.TESTER],
               "worker.md": [wt.WORKER], "reviewer.md": [wt.OK],
               "reviewer-runs.md": [wt.OK]}
    writes = {"tester.md": [("tests/test_mul.py", wt.RIGHT)],
              "worker.md": [("calc.py", wt.AFTER)]}
    live, scored = shipped_both(tmp_path, monkeypatch, answers, writes)
    assert "reviewer-runs.md" not in live
    assert scored == live


def test_an_eval_of_a_flow_with_preflight_holds_the_step_a_run_holds(
        tmp_path, monkeypatch, fake_cli):
    live, scored = both(tmp_path, monkeypatch, fake_cli, "risky",
                        ["planner", PARKS, "reviewer"], NO_MAP,
                        [answer("- edit a.py\n"), answer("done\n"),
                         answer("VERDICT: ok\n\nfine\n")])
    assert [l["outcome"] for l in live] == ["ok", "parked"]
    assert shape(scored) == shape(live)
