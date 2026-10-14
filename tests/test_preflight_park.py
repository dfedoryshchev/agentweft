"""a hot blast radius parks the run for a person, as a third preflight answer.

flag lets the edit through and refuse throws the work away. park keeps what the
step produced and stops before anything acts on it, so the risky edit becomes a
person's call rather than the agent's or nobody's.
"""
import json
import sys

from agentweft.runner import engine, prompts, resume, state, stops as causes, trace

NL = chr(10)
RANKING = "src/hooks.ts 0.94" + NL + "src/util.ts 0.11" + NL
HOT = "i will rewrite src/hooks.ts"


def a_flow(tmp_path, mode, threshold=0.7, name="hotpark"):
    root = tmp_path / "flows"
    d = root / name
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(
        "name: " + name + NL
        + "steps:" + NL
        + "  - role: planner" + NL
        + "    prompt: planner.md" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL
        + "    preflight:" + NL
        + "      mode: " + mode + NL
        + "      threshold: " + str(threshold) + NL
        + "  - role: reviewer" + NL
        + "    prompt: reviewer.md" + NL
        + "provider:" + NL
        + "  provider: fake" + NL
        + "context:" + NL
        + "  command: [\"not-a-real-server\"]" + NL
        + "  tool: hotspots" + NL,
        encoding="utf-8")
    (d / "instructions.md").write_text("three steps." + NL, encoding="utf-8")
    for role in ("planner", "worker", "reviewer"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    return root


def go(tmp_path, monkeypatch, mode, worker=HOT, threshold=0.7,
       ranking=(RANKING, ""), extra=()):
    """run main() over a throwaway flow, and hand back (step, prompt) asked."""
    root = tmp_path / "flows"
    if not root.exists():
        a_flow(tmp_path, mode, threshold)
    asked = []
    answers = {"planner.md": "look at the hooks", "worker.md": worker,
               "reviewer.md": "VERDICT: ok"}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        return answers[step], False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(engine.context, "risk_map",
                        lambda conf, where=None: ranking)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(resume, "JOURNAL", None)
    monkeypatch.setattr(sys, "argv", ["run.py", "hotpark", "--force",
                                      "--flows", str(root)] + list(extra))
    monkeypatch.chdir(tmp_path)
    engine.main()
    return asked


def steps_asked(asked):
    return [step for step, _ in asked]


def journal():
    return (state.RUNS / "journal.md").read_text(encoding="utf-8")


def index():
    return (state.RUNS / "index.md").read_text(encoding="utf-8")


def the_run():
    [run_dir] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    return run_dir


def handoff():
    return (the_run() / "handoff.md").read_text(encoding="utf-8")


def test_park_stops_before_the_next_step_and_says_so(tmp_path, monkeypatch,
                                                     capsys):
    asked = go(tmp_path, monkeypatch, "park")
    assert steps_asked(asked) == ["planner.md", "worker.md"]
    said = capsys.readouterr().out
    assert "parked at worker.md, waiting for user" in said
    assert "parked at worker.md" in journal()
    assert "src/hooks.ts (0.94)" in journal()
    assert "PARKED  hotpark  at worker.md" in index()


def test_the_park_note_names_the_hot_files_and_their_scores(tmp_path,
                                                            monkeypatch):
    go(tmp_path, monkeypatch, "park",
       worker="i will rewrite src/hooks.ts and src/util.ts")
    note = handoff()
    assert "src/hooks.ts (0.94)" in note
    assert "src/util.ts" not in note
    assert "reviewer.md" in note
    assert "--resume" in note


def test_the_parked_step_gets_its_line_in_the_step_record(tmp_path,
                                                          monkeypatch):
    go(tmp_path, monkeypatch, "park")
    lines = [json.loads(l) for l in (the_run() / trace.FILE)
             .read_text(encoding="utf-8").split(NL) if l.strip()]
    assert [(l["step"], l["outcome"]) for l in lines] == [
        ("planner.md", "ok"), ("worker.md", "parked")]
    assert "src/hooks.ts (0.94)" in lines[-1]["why"]
    assert lines[-1]["to"] is None


def test_a_score_at_the_threshold_parks(tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, "park", threshold=0.94)
    assert "reviewer.md" not in steps_asked(asked)
    assert "parked at worker.md" in journal()


def test_a_score_below_the_threshold_runs_through(tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, "park", threshold=0.95)
    assert steps_asked(asked) == ["planner.md", "worker.md", "reviewer.md"]
    assert "parked" not in journal() and "  ok  " in journal()


def test_a_step_that_names_no_hot_file_runs_through(tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, "park", worker="tidy src/util.ts")
    assert steps_asked(asked) == ["planner.md", "worker.md", "reviewer.md"]
    assert "parked" not in journal()


def test_no_ranking_parks_a_step_set_to_park(tmp_path, monkeypatch, capsys):
    asked = go(tmp_path, monkeypatch, "park", ranking=("", "server is down"))
    assert steps_asked(asked) == ["planner.md", "worker.md"]
    said = capsys.readouterr().out
    assert "no risk map: server is down" in said
    assert "parked at worker.md, waiting for user" in said
    assert "no ranking to check against" in journal()
    assert "no ranking to check against" in handoff()


def test_no_ranking_parks_a_step_set_to_refuse_rather_than_refusing_it(
        tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, "refuse", ranking=("", "server is down"))
    assert steps_asked(asked) == ["planner.md", "worker.md"]
    last = causes.read(journal().strip().split(NL)[-1])
    assert (last.status, last.cause) == ("parked at worker.md", "parked")
    assert "hot blast radius" not in journal()


def test_no_ranking_is_said_and_a_flag_step_carries_on(tmp_path, monkeypatch,
                                                       capsys):
    asked = go(tmp_path, monkeypatch, "flag", ranking=("", "server is down"))
    assert steps_asked(asked) == ["planner.md", "worker.md", "reviewer.md"]
    assert "preflight: no ranking to check against, worker.md not checked" \
        in capsys.readouterr().out
    assert "parked" not in journal()


def test_a_resumed_run_past_the_planner_does_not_pass_a_park_step_silently(
        tmp_path, monkeypatch, capsys):
    go(tmp_path, monkeypatch, "park", worker="")
    assert "failed at worker.md" in journal()
    capsys.readouterr()
    asked = go(tmp_path, monkeypatch, "park", extra=["--resume"])
    assert steps_asked(asked) == ["worker.md"]
    said = capsys.readouterr().out
    assert "no ranking to check against" in said
    assert "parked at worker.md, waiting for user" in said


def test_each_mode_stops_its_own_way_on_the_same_hot_step(tmp_path,
                                                          monkeypatch):
    stops = {}
    for mode in ("flag", "refuse", "park"):
        here = tmp_path / mode
        here.mkdir()
        monkeypatch.setattr(state, "RUNS", here / "runs")
        asked = go(here, monkeypatch, mode)
        last = causes.read(journal().strip().split(NL)[-1])
        stops[mode] = (steps_asked(asked)[-1], last.status, last.cause)
    assert stops["flag"] == ("reviewer.md", "ok", None)
    assert stops["refuse"] == ("worker.md", "failed at worker.md", "refused")
    assert stops["park"] == ("worker.md", "parked at worker.md", "parked")


def test_a_resumed_park_carries_on_with_what_the_parked_step_wrote(
        tmp_path, monkeypatch, capsys):
    go(tmp_path, monkeypatch, "park")
    run_dir = the_run()
    (run_dir / "worker.md").write_text("only touch src/util.ts after all",
                                       encoding="utf-8")
    asked = go(tmp_path, monkeypatch, "park", extra=["--resume"])
    assert steps_asked(asked) == ["reviewer.md"]
    assert "only touch src/util.ts after all" in asked[0][1]
    assert "picking " + run_dir.name + " up at reviewer.md" \
        in capsys.readouterr().out
    lines = [l for l in journal().strip().split(NL) if "  running  " not in l]
    assert "parked at worker.md" in lines[0]
    assert "ok (resumed)" in lines[1]
