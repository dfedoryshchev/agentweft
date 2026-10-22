"""the shipped fix-with-test flow end to end, on fake answers and a real pytest.

each step's answer is canned, and the worker and the patcher write into the
project the way a model with a shell would. the gates are the flow's own.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.guardrails import gates
from agentweft.guardrails.gates.command_gate import CommandGate
from agentweft.providers import cli_provider, fake_provider
from agentweft.roles import resolver
from agentweft.runner import engine, prompts, resume, state

NL = chr(10)
# the shipped flow looks back after every run that ends, once, last
RETRO = "retro.md"
FLOWS = Path(__file__).resolve().parents[1] / "flows"
NODE = "tests/test_calc.py::test_add"
BROKEN = "def add(a, b):" + NL + "    return a - b" + NL
# not the same size as BROKEN: written in the same second at the same size,
# the stale .pyc from the red run is what the green run imports.
FIXED = "def add(a, b):" + NL + "    return sum((a, b))" + NL
TEST = ("from calc import add" + NL + NL + NL
        + "def test_add():" + NL + "    assert add(1, 2) == 3" + NL)
WORKER = "FAILS: assert -1 == 3" + NL + "TEST: " + NODE + NL
PATCHER = "TEST: " + NODE + NL + "return a + b"
VERIFIED = "PASS the patch is the smallest thing that turns it green"


def shipped_gates(step):
    fm = runner.config("fix-with-test")
    by_role = resolver.resolve(fm.raw, runner.flow_path("fix-with-test"))
    return runner.Run("fix-with-test", fm, by_role).gates_for(step)


def judged(tmp_path):
    """-> a flows folder holding fix-with-test with its judge switched on."""
    root = tmp_path / "flows"
    shutil.copytree(FLOWS / "fix-with-test", root / "fix-with-test")
    yml = root / "fix-with-test" / "flow.yaml"
    yml.write_text(yml.read_text(encoding="utf-8").replace(
        'verify: "off"', "verify: judge"), encoding="utf-8")
    return root


def verdict_gates(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(judged(tmp_path))])
    return [g for g in shipped_gates("verify.md")
            if not isinstance(g, CommandGate)]


def test_the_judged_verify_gate_passes_its_one_pass(tmp_path, monkeypatch):
    assert all(g.run(VERIFIED) for g in verdict_gates(tmp_path, monkeypatch))


def test_the_judged_verify_gate_fails_a_bulleted_fail(tmp_path, monkeypatch):
    answer = "- FAIL: the patch is the smallest thing - it also renames add"
    assert not all(g.run(answer)
                   for g in verdict_gates(tmp_path, monkeypatch))


def test_the_judged_verify_gate_fails_an_answer_that_is_not_a_verdict(
        tmp_path, monkeypatch):
    answer = "UNVERIFIED: could not run the suite"
    assert not all(g.run(answer)
                   for g in verdict_gates(tmp_path, monkeypatch))


def test_the_judged_verify_step_runs_no_suite_of_its_own(tmp_path,
                                                        monkeypatch):
    """the suite is the patcher's gate, so it runs with the judge off too."""
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(judged(tmp_path))])
    assert not [g for g in shipped_gates("verify.md")
                if isinstance(g, CommandGate)]


def test_the_shipped_patcher_has_a_green_red_test_gate():
    built = [g for g in shipped_gates("patcher.md")
             if isinstance(g, gates.registry["red-test"])]
    assert len(built) == 1
    assert built[0].run("patched" + NL + "FAILS: still red").ok is False
    assert "{test}" in built[0].opts["command"]


def test_the_patcher_is_asked_to_name_the_test_it_made_pass():
    text = (runner.flow_path("fix-with-test") / "patcher.md").read_text(
        encoding="utf-8")
    assert "TEST:" in text


def run_it(tmp_path, monkeypatch, answers, fixes=True, flows=FLOWS):
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "calc.py").write_text(BROKEN, encoding="utf-8")
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if step == "worker.md":
            (project / "tests" / "test_calc.py").write_text(TEST,
                                                            encoding="utf-8")
        if step == "patcher.md" and fixes:
            (project / "calc.py").write_text(FIXED, encoding="utf-8")
        if step == RETRO:
            return fake_provider.NOTHING_TO_KEEP, False
        return answers.get(step, ""), False

    monkeypatch.setattr(engine, "call", fake_call)
    # the retro is granted only to read, and a step with a grant is refused
    # unless the cli's version holds it to that grant
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--flows", str(flows),
                                      "--workdir", "project",
                                      "--task", "add(1, 2) returns -1"])
    engine.main()
    written = "".join((p / "gates.md").read_text(encoding="utf-8")
                      for p in (tmp_path / "runs").iterdir()
                      if (p / "gates.md").exists())
    return asked, written


def test_red_on_a_node_id_then_green_then_the_suite(tmp_path, monkeypatch):
    asked, written = run_it(tmp_path, monkeypatch, {
        "worker.md": WORKER, "patcher.md": PATCHER})
    assert asked == ["worker.md", "patcher.md", RETRO], written
    assert "FAIL " not in written
    assert "PASS command - exit 0" in written.split("## patcher.md")[1]


def test_a_patcher_that_names_no_test_is_held_to_the_workers(tmp_path,
                                                             monkeypatch):
    asked, written = run_it(tmp_path, monkeypatch, {
        "worker.md": WORKER, "patcher.md": "return a + b"})
    assert asked == ["worker.md", "patcher.md", RETRO], written
    assert "PASS red-test - green, exit 0" in written.split("## patcher.md")[1]


def test_a_patcher_that_names_no_test_and_fixes_nothing_stops(tmp_path,
                                                              monkeypatch):
    asked, written = run_it(tmp_path, monkeypatch, {
        "worker.md": WORKER, "patcher.md": "return a + b"}, fixes=False)
    assert asked == ["worker.md", "patcher.md", "patcher.md", RETRO]
    assert "wanted 0" in written.split("## patcher.md")[1]


def test_a_patch_that_leaves_the_test_red_stops_at_the_patcher(tmp_path,
                                                              monkeypatch):
    asked, written = run_it(tmp_path, monkeypatch, {
        "worker.md": WORKER, "patcher.md": PATCHER}, fixes=False)
    assert asked == ["worker.md", "patcher.md", "patcher.md", RETRO]
    assert "FAIL red-test" in written.split("## patcher.md")[1]


def test_with_the_judge_on_a_bulleted_fail_stops_the_run(tmp_path,
                                                         monkeypatch):
    answer = "- FAIL: the patch is not the smallest thing that turns it green"
    asked, written = run_it(tmp_path, monkeypatch, {
        "worker.md": WORKER, "patcher.md": PATCHER, "verify.md": answer},
        flows=judged(tmp_path))
    assert asked == ["worker.md", "patcher.md", "verify.md", "verify.md",
                     RETRO]
    assert "FAIL verdict" in written


def test_with_the_judge_on_an_unverified_answer_stops_the_run(tmp_path,
                                                              monkeypatch):
    asked, written = run_it(tmp_path, monkeypatch, {
        "worker.md": WORKER, "patcher.md": PATCHER,
        "verify.md": "UNVERIFIED: could not run the suite"},
        flows=judged(tmp_path))
    assert "FAIL verdict" in written


def test_with_the_judge_on_an_unsure_check_finishes_with_it_on_record(
        tmp_path, monkeypatch, capsys):
    unsure = "UNSURE: cannot tell if a smaller patch covers the negative case"
    answer = VERIFIED + NL + unsure
    asked, written = run_it(tmp_path, monkeypatch, {
        "worker.md": WORKER, "patcher.md": PATCHER, "verify.md": answer},
        flows=judged(tmp_path))
    assert asked == ["worker.md", "patcher.md", "verify.md", RETRO], written
    assert "FAIL verdict" not in written
    assert "1 unproven" in written
    folder = next(p for p in (tmp_path / "runs").iterdir()
                  if (p / "steps.jsonl").exists())
    handed = (folder / "handoff.md").read_text(encoding="utf-8")
    assert handed.split(NL)[0].endswith(": done, 1 check unproven")
    assert "- verify.md unproven: " + unsure in handed
    lines = [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").split(NL) if l.strip()]
    judged_gates = [g for l in lines if l["step"] == "verify.md"
                    for g in l["gates"] if g["gate"] == "verdict"]
    assert judged_gates[0]["ok"] is True
    assert judged_gates[0]["unproven"] == [unsure]
    assert "done, 1 check unproven" in capsys.readouterr().out
    kept = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert kept["outcome"] == "done, 1 check unproven"


def test_an_empty_worker_answer_is_reported_as_nothing(tmp_path, monkeypatch):
    asked, written = run_it(tmp_path, monkeypatch, {"worker.md": ""})
    assert asked == ["worker.md", RETRO]
    # the run stops on the empty answer itself, before the red-test gate can
    # report on an answer that never came
    assert written == ""
    journal = (tmp_path / "runs" / "journal.md").read_text(encoding="utf-8")
    assert "  failed at worker.md  " in journal
    assert "  no answer  " in journal
    assert "nothing came out of worker.md" in journal
    assert "never failed" not in written
