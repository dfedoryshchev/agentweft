"""every pass says what it won: the defect its gate or verdict caught, the
stop it made, the proof a program check gave, the question it decided, or
nothing. the retro puts each step's money and seconds against that, and
`python run.py spend` keeps a provider's own figure apart from the table's."""
import datetime
import json
import subprocess
import sys
import types
from decimal import Decimal

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


def won(outcome, gates=(), cause=None, to=None, step="reviewer.md",
        **record):
    entry = trace.Entry(1, step, [], Said(), None, None, False)
    entry.gates = list(gates)
    for k, v in record.items():
        setattr(entry, k, v)
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


def test_the_pass_that_wrote_the_red_proof_proved():
    assert won("ok", [a_gate("red-test", True, "red, exit 1")],
               step="tester.md", proved=True) == "proved"
    assert won("ok", [a_gate("red-test", True,
                             "red, as claimed - nothing was run")],
               step="worker.md") == "none"


def test_a_lead_whose_decision_is_on_record_decided():
    assert won("decided", to="worker.md", step="lead.md",
               decided=True) == "decided"
    assert won("escalated", step="lead.md") == "none"


def test_a_stop_that_left_the_steps_work_in_the_tree_delivered():
    assert won("parked", cause="parked", changed=True) == "delivered"
    assert won("conflict", cause="conflict", changed=False) == "stopped"
    assert won("parked", cause="budget", changed=True) == "none"


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


def lines_of(folder):
    return [json.loads(l) for l in (folder / trace.FILE).read_text(
        encoding="utf-8").split("\n") if l.strip()]


def test_a_gate_that_could_not_run_caught_nothing():
    from agentweft.guardrails.gates.command_gate import CommandGate

    gate = CommandGate(command=["agentweft-no-such-program"], expect=0)
    could_not = gate.run("did it\n")
    assert not could_not.ok
    assert won("gate failed", [could_not], to="worker.md") == "none"
    assert won("gate failed", [could_not, a_gate("length", False, "9 lines")],
               to="worker.md") == "caught"


def test_a_step_that_changed_the_tree_and_then_parked_did_not_stop(
        tmp_path, monkeypatch):
    import test_lead

    escalate = "ESCALATE: not mine to say" + test_lead.NL
    _, _, code, folder, _ = test_lead.run_it(
        tmp_path, monkeypatch, "build-feature",
        {"planner.md": [test_lead.PLAN, escalate],
         "tester.md": [test_lead.TESTER], "worker.md": [test_lead.NEEDS]},
        {"tester.md": [("tests/test_mul.py", test_lead.TEST)],
         "worker.md": [("calc.py", test_lead.AFTER)]})
    assert code == stops.EXIT_STOP
    [asked] = [l for l in lines_of(folder) if l["outcome"] == "parked"]
    assert asked["step"] == "worker.md"
    assert asked["won"] == "delivered"


def test_a_step_that_parked_with_the_tree_as_it_found_it_stopped(
        tmp_path, monkeypatch):
    import test_lead

    escalate = "ESCALATE: not mine to say" + test_lead.NL
    _, _, code, folder, _ = test_lead.run_it(
        tmp_path, monkeypatch, "build-feature",
        {"planner.md": [test_lead.PLAN, escalate],
         "tester.md": [test_lead.TESTER], "worker.md": [test_lead.NEEDS]},
        {"tester.md": [("tests/test_mul.py", test_lead.TEST)]})
    assert code == stops.EXIT_STOP
    [asked] = [l for l in lines_of(folder) if l["outcome"] == "parked"]
    assert (asked["step"], asked["won"]) == ("worker.md", "stopped")


def test_a_lead_decision_that_held_is_decided_and_the_red_proof_names_who_proved(
        tmp_path, monkeypatch):
    import test_lead

    _, _, code, folder, _ = test_lead.build(tmp_path, monkeypatch,
                                            [test_lead.DECIDED])
    assert code == stops.EXIT_OK
    proof = json.loads((folder / "red-proof.json").read_text(
        encoding="utf-8"))["proof"]
    assert proof["step"] == "tester.md"
    assert [(l["step"], l["outcome"], l["won"])
            for l in lines_of(folder)] == [
        ("planner.md", "ok", "none"), ("tester.md", "ok", "proved"),
        ("worker.md", "asked", "none"), ("planner.md", "decided", "decided"),
        ("worker.md", "ok", "delivered"), ("reviewer.md", "ok", "none"),
        ("reviewer-runs.md", "ok", "none"), ("retro.md", "ok", "none")]


def test_a_decided_the_runner_did_not_hold_is_neither_decided_nor_escalated(
        tmp_path, monkeypatch):
    import test_lead

    _, _, code, folder, _ = test_lead.build(tmp_path, monkeypatch, [
        "DECIDED: keep: return the product as it is" + test_lead.NL])
    assert code == stops.EXIT_STOP
    lead_line = [l for l in lines_of(folder) if l["step"] == "planner.md"][-1]
    assert lead_line["outcome"] == "overruled"
    assert "no why: line" in lead_line["why"]
    assert lead_line["won"] == "none"


def test_a_won_from_the_words_alone_is_none():
    assert won("decided", to="worker.md", step="lead.md") == "none"
    assert won("ok", [a_gate("command", True, "exit 0")]) == "none"
    assert won("ok", [a_gate("red-test", True, "red, exit 1")],
               step="worker.md") == "none"


def test_a_pass_whose_work_is_in_the_place_and_a_gate_passed_delivered():
    command = {"gate": "command", "ok": True, "detail": "exit 0"}
    assert trace.won("ok", None, [command], "next.md",
                     changed=True) == "delivered"
    assert trace.won("ok", None, [command], "next.md",
                     changed=False) == "none"
    assert trace.won("ok", None, [command], "next.md") == "none"
    assert trace.won("ok", None, [], "next.md", changed=True) == "none"
    assert trace.won("ok", None, [dict(command, skipped=True)], "next.md",
                     changed=True) == "none"
    assert trace.won("ok", None, [dict(command, broke=True)], "next.md",
                     changed=True) == "none"
    assert trace.won("ok", None, [command], "next.md", proved=True,
                     changed=True) == "proved"


def test_a_passing_gate_that_could_not_do_its_job_proved_nothing():
    unreplayed = {"gate": "red-first", "ok": True,
                  "detail": "not replayed - the run took no start snapshot",
                  "issue": "red-first could not replay: the run took no start"
                           " snapshot"}
    assert trace.won("ok", None, [unreplayed], "next.md",
                     changed=True) == "none"
    command = {"gate": "command", "ok": True, "detail": "exit 0"}
    assert trace.won("ok", None, [unreplayed, command], "next.md",
                     changed=True) == "delivered"


def test_the_shipped_fix_flows_patcher_delivered_and_its_worker_proved(
        tmp_path, monkeypatch, capsys):
    import test_golden

    test_golden.replay("fix-with-test",
                       test_golden.CASES[("fix-with-test", "pass")],
                       tmp_path, monkeypatch, capsys)
    [folder] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    assert [(l["step"], l["outcome"], l["won"])
            for l in lines_of(folder)] == [
        ("worker.md", "ok", "proved"), ("patcher.md", "ok", "delivered"),
        ("retro.md", "ok", "none")]


def test_an_old_line_of_one_kind_is_not_called_mixed():
    g = spend.Group()
    g.add("r1", {"step": "a", "tokens": {"counted": False}, "cost": 0.5,
                 "priced": None, "cost_from": {"transcript": 2}})
    assert (g.table_priced, g.unsplit) == (Decimal("0.5"), 0)


def test_an_old_line_of_two_kinds_is_still_mixed():
    g = spend.Group()
    g.add("r1", {"step": "a", "tokens": {"counted": False}, "cost": 0.5,
                 "priced": None,
                 "cost_from": {"provider": 1, "estimate": 1}})
    assert (g.table_priced, g.estimated, g.unsplit) == (0, 0, Decimal("0.5"))


def a_line(outcome="ok", block=None, gates=(), cause=None, why=None,
           step="reviewer.md"):
    entry = trace.Entry(1, step, [], Said(), None, None, False)
    entry.gates = list(gates)
    entry.handoff = block
    return trace.line(entry, outcome, why=why, cause=cause)


def verified(*backed):
    return {"state": "present", "verified": [
        {"claim": "claim " + str(n), "backed": b, "by": "command"}
        for n, b in enumerate(backed)]}


def test_a_reviewer_that_found_nothing_says_how_much_it_checked():
    five = a_line(block=verified("backed", "backed", "backed", "backed",
                                 "backed", "unbacked", "unchecked"))
    assert (five["won"], five["checked"]) == ("none", 5)
    none = a_line(block=verified("unbacked", "ran"))
    assert (none["won"], none["checked"]) == ("none", 0)
    gated = a_line(block=verified("backed"), gates=[
        a_gate("length", True, "2 lines")])
    assert gated["checked"] == 2


def test_a_gate_that_refused_says_what_it_prevented():
    said = a_line(gates=[a_gate("writes", False, "writes nothing and changed"
                                " product code: o.txt"),
                         a_gate("length", True, "2 lines")])
    refused, passed = said["gates"]
    assert refused["prevented"] == ("writes nothing and changed product"
                                    " code: o.txt")
    assert "prevented" not in passed


def test_a_police_stop_says_what_it_prevented():
    said = a_line("stopped", cause=stops.OFF_TASK,
                  why="worker.md reached a host the flow does not allow")
    assert said["prevented"] == ("worker.md reached a host the flow does not"
                                 " allow")
    assert "prevented" not in a_line()


def a_pass_of(step, cost, won, checked=None, **more):
    facts = dict({"cost": cost, "won": won, "checked": checked}, **more)
    return {"step": step, "seconds": 1.0, "outcome": "ok", "gates": [],
            "facts": facts}


def test_the_retro_reads_what_it_wrote():
    retro = a_pass_of("retro.md", 0.05, "none", 0, kept_facts={
        "written": ["F-0001", "F-0002"], "refused": [{"item": "fact on a",
                                                     "why": "no evidence"}]})
    assert summary.won_words(retro) == \
        ", won facts 2, docs 0, guards 0 (1 refused)"
    retro["facts"]["kept_facts"]["applied"] = [
        {"path": "README.md", "kind": "doc"},
        {"path": "CLAUDE.md", "kind": "instruction"},
        {"path": "tests/test_g.py", "kind": "guard"}]
    assert summary.won_words(retro) == \
        ", won facts 2, docs 2, guards 1 (1 refused)"
    assert summary.won_words(a_pass_of("reviewer.md", 0.2, "none", 9)) == \
        ", won none, checked 9"
    assert summary.won_words(a_pass_of("worker.md", 0.1, "delivered", 3)) == \
        ", won delivered"


def test_the_spend_on_passes_that_won_nothing_is_split_by_what_they_checked():
    passes = [a_pass_of("worker.md", 0.1, "delivered", 2),
              a_pass_of("reviewer.md", 0.2, "none", 5),
              a_pass_of("reviewer-runs.md", 0.3, "none", 0),
              a_pass_of("worker.md", 0.15, "caught", 1, prevented=["writes"]),
              a_pass_of("retro.md", 0.05, "none", 0)]
    said = summary.bought(passes)
    assert "- prevented: 1 refusal (writes: 1)" in said
    assert ("- USD on steps that won nothing and checked nothing: $0.3000 of"
            " $0.8000") in said
    assert "- USD on steps that won nothing and checked 5: $0.2000" in said
    assert "- upkeep, not waste: the retro $0.0500" in said
    assert said[-1].startswith("- total: 5 passes")


def test_a_pass_whose_cost_was_not_stated_is_named_on_the_waste_lines():
    passes = [a_pass_of("worker.md", 0.5, "delivered", 2),
              a_pass_of("reviewer.md", None, "none", 0),
              a_pass_of("reviewer-runs.md", None, "none", 4)]
    said = summary.bought(passes)
    assert ("- USD on steps that won nothing and checked nothing: $0.0000 of"
            " $0.5000, cost not stated on 1") in said
    assert ("- USD on steps that won nothing and checked 4: $0.0000, cost not"
            " stated on 1") in said
