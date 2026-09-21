"""a scored run goes through the checks the flow declares.

the harness had its own way through a flow, and that way ran no gates and did
not ask the router whether a step had produced what it was required to. a flow
whose gate stops every real run scored as though the gate had passed, which is
the one thing a comparison between two prompts must not do.
"""
import sys

sys.path.insert(0, ".")
from agentweft.evals import harness
from agentweft.runner import engine, prompts

NL = chr(10)
THREE = "one" + NL + "two" + NL + "three"

HEAD = ("name: {name}" + NL
        + "steps:" + NL
        + "  - role: planner" + NL
        + "    prompt: planner.md" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL)
TAIL = ("  - role: merge" + NL
        + "    prompt: merge.md" + NL
        + "journal: false" + NL
        + "provider:" + NL
        + "  provider: fake" + NL)
CAP = ("    gates:" + NL
       + "      - gate: length" + NL
       + "        max_lines: 1" + NL)
MUST = "    must_produce: \"FAILS:\"" + NL


def a_flow(tmp_path, body, name):
    root = tmp_path / "flows"
    d = root / name
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    (d / "instructions.md").write_text("do the thing you are given." + NL,
                                       encoding="utf-8")
    for role in ("planner", "worker", "merge"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    return root


def go(tmp_path, monkeypatch, body, answers, name):
    """score a throwaway flow the way the harness does.

    -> (the steps that were asked, the output the harness would score).
    """
    root = a_flow(tmp_path, body, name)
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        return answers.get(step, "nothing to report"), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.chdir(tmp_path)
    out, budget = harness.run_flow_for(
        name, {"inbox": tmp_path, "provider": {"provider": "fake"}})
    return asked, out


def test_a_failing_gate_stops_the_scored_run(tmp_path, monkeypatch):
    body = HEAD.format(name="scored-gate") + CAP + TAIL
    asked, out = go(tmp_path, monkeypatch, body,
                    {"worker.md": THREE}, "scored-gate")
    assert "worker.md" in asked
    assert "merge.md" not in asked


def test_the_score_is_taken_from_where_the_gate_stopped(tmp_path, monkeypatch):
    """the number the harness writes down is about this text, so it has to be
    the text the run actually got to."""
    body = HEAD.format(name="scored-gate-out") + CAP + TAIL
    asked, out = go(tmp_path, monkeypatch, body,
                    {"worker.md": THREE, "merge.md": "merged"},
                    "scored-gate-out")
    assert out == THREE


def test_a_step_that_did_not_produce_what_it_must_stops_the_scored_run(
        tmp_path, monkeypatch):
    body = HEAD.format(name="scored-must") + MUST + TAIL
    asked, out = go(tmp_path, monkeypatch, body,
                    {"worker.md": "no failing test here"}, "scored-must")
    assert "merge.md" not in asked


def test_a_gate_that_passes_lets_the_scored_run_finish(tmp_path, monkeypatch):
    body = HEAD.format(name="scored-ok") + CAP + TAIL
    asked, out = go(tmp_path, monkeypatch, body,
                    {"worker.md": "one line", "merge.md": "merged"},
                    "scored-ok")
    assert "merge.md" in asked
    assert out == "merged"
