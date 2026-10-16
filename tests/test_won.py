"""every pass says what it won: the defect its gate or verdict caught, the
stop it made, the proof a program check gave, the question it decided, or
nothing. the retro puts each step's money and seconds against that, and
`python run.py spend` keeps a provider's own figure apart from the table's."""
import datetime
import json
import subprocess
import sys
import types

sys.path.insert(0, ".")
from agentweft.runner import engine, handoff, spend, stops, summary, trace

import test_prices
from test_handoff_from_runner import a_pass
from test_stops import a_flow, answer, steps_of, the_folder
from test_trace import no_waiting

WORKER = "fixed it\n"
REDO = "VERDICT: redo\n\nnotes.md still says three\n"
OK = "VERDICT: ok\n\nfine\n"


class Said(object):
    name = "cli"
    command = "claude"
    choice = None

    def asks_for(self):
        return "m-small"

    def granted(self):
        return None


def a_gate(gate, ok, detail):
    return types.SimpleNamespace(gate=gate, ok=ok, detail=detail,
                                 unproven=None)


def won(outcome, gates=(), cause=None, to=None, step="reviewer.md"):
    entry = trace.Entry(1, step, [], Said(), None, None, False)
    entry.gates = list(gates)
    return trace.line(entry, outcome, cause=cause, to=to).get("won")


def test_a_reviewer_that_sends_the_work_back_once_caught_something(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "two", ["worker", "reviewer"])
    fake_cli(answer(WORKER, session="w-1"), answer(REDO, session="r-1"),
             answer("fixed the notes too\n", session="w-2"),
             answer(OK, session="r-2"))
    assert engine.main() == 0
    lines = steps_of(the_folder())
    assert [(l["step"], l["outcome"], l.get("won")) for l in lines] == [
        ("worker.md", "ok", "none"), ("reviewer.md", "redo", "caught"),
        ("worker.md", "ok", "none"), ("reviewer.md", "ok", "none")]


def test_an_all_pass_judge_won_nothing():
    assert won("ok", [a_gate("verdict", True, "ok")]) == "none"


def test_a_failed_gate_caught_and_a_conflict_stopped():
    assert won("gate failed", [a_gate("command", False, "exit 1")],
               to="worker.md") == "caught"
    assert won("conflict", cause="conflict") == "stopped"
    assert won("refused", cause="refused") == "stopped"
    assert won("parked", cause="parked") == "stopped"
    assert won("parked", cause="budget") == "none"
    assert won("crashed", cause="exception") == "none"


def test_a_program_check_that_passed_proved_and_a_claim_did_not():
    assert won("ok", [a_gate("red-test", True, "red, exit 1")],
               step="worker.md") == "proved"
    assert won("ok", [a_gate("command", True, "exit 0")]) == "proved"
    assert won("ok", [a_gate("red-test", True,
                             "red, as claimed - nothing was run")],
               step="worker.md") == "none"
    assert won("ok", [a_gate("red-first", True,
                             "not replayed: no new test")]) == "none"


def test_a_lead_that_decided_won_a_decision():
    assert won("decided", to="worker.md", step="lead.md") == "decided"
    assert won("escalated", step="lead.md") == "none"


def test_the_retro_puts_money_and_seconds_against_what_each_step_won():
    passes = [a_pass("worker.md", facts={"cost": 0.5, "won": "none"}),
              a_pass("reviewer.md", "redo", facts={"cost": 0.25,
                                                   "won": "caught"}),
              a_pass("worker.md", facts={"cost": 0.5, "won": "proved"}),
              a_pass("reviewer.md", facts={"cost": 0.25, "won": "none"})]
    lines = summary.retro(passes)
    assert lines[1] == "- reviewer.md 1.0s ($0.2500), won caught: sent back"
    assert "- won caught: 1 pass, 1.0s, $0.2500" in lines
    assert "- won proved: 1 pass, 1.0s, $0.5000" in lines
    assert "- won none: 2 passes, 2.0s, $0.7500" in lines
    assert "- total: 4 passes, 4.0s, $1.5000" in lines


def test_the_retro_totals_say_when_a_step_stated_no_cost():
    passes = [a_pass("worker.md", facts={"cost": 0.5, "won": "none"}),
              a_pass("reviewer.md", facts={"cost": None, "won": "none"})]
    lines = summary.retro(passes)
    assert "- won none: 2 passes, 2.0s, $0.5000, cost not stated on 1" \
        in lines
    assert "- total: 2 passes, 2.0s, $0.5000, cost not stated on 1" in lines


def test_a_step_line_keeps_what_each_figure_in_its_cost_came_to(
        tmp_path, monkeypatch, fake_cli):
    test_prices.a_flow(tmp_path, monkeypatch, "slow", ["worker"], "m-small")
    monkeypatch.setattr(handoff, "PROJECTS", tmp_path / "nothing")
    no_waiting(monkeypatch)
    cli_ = fake_cli((subprocess.TimeoutExpired("claude", 600), b"", b""),
                    test_prices.answer("did it\n", "m-small", 0.005,
                                       input_tokens=1000, output_tokens=800))
    assert engine.main() == 0
    [step] = steps_of(the_folder())
    sent = cli_.calls[0]["stdin"].decode("utf-8")
    first = round((len(sent) // 4) / 1000000.0, 6)
    assert step.get("cost_parts") == {"provider": 0.005, "estimate": first}


def a_run(runs, name, steps):
    folder = runs / name
    folder.mkdir(parents=True)
    (folder / trace.FILE).write_text(
        "\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")
    now = datetime.datetime(2026, 1, 22, 9, 0)
    return stops.line(now, "two", "ok", 40, name, saved="o.md",
                      spend="2 calls, $0.6500")


def test_spend_keeps_reported_table_priced_and_estimated_apart(tmp_path):
    runs = tmp_path / "runs"
    counted = {"counted": True, "input": 1, "output": 1, "cache_read": 0,
               "cache_creation": 0}
    line = a_run(runs, "r1", [
        {"provider": "cli", "tokens": counted, "cost": 0.25, "priced": 0.25,
         "cost_from": None},
        {"provider": "cli", "tokens": counted, "cost": 0.4, "priced": 0.4,
         "cost_from": {"provider": 1, "transcript": 1, "estimate": 1},
         "cost_parts": {"provider": 0.25, "transcript": 0.1,
                        "estimate": 0.05}}])
    (runs / "journal.md").write_text(line + "\n", encoding="utf-8")
    out = "\n".join(spend.report(runs))
    assert "reported $0.5000, table-priced $0.1000, estimated $0.0500" in out


def test_a_gate_skipped_by_name_proved_nothing():
    for gate in ("command", "coverage", "red-test", "red-first"):
        g = {"gate": gate, "ok": True, "skipped": True,
             "detail": "not run - skipped: the pattern predates the format"}
        assert trace.won("ok", None, [g], "next.md") == "none", gate


def test_the_handoff_never_says_a_skipped_red_first_was_shown():
    p = {"step": "worker.md", "gates": [
        {"gate": "red-first", "ok": True, "skipped": True,
         "detail": "not run - skipped: no replay here", "command": None}]}
    assert summary.red_first([p]) == "not proven by a gate"
