"""the closing step of fix-with-test runs the suite rather than reading about it.

the flow promised that the patch turns the test green and then asked a model
whether it had. the check that says so now shells out.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.guardrails.gates.command_gate import CommandGate
from agentweft.roles import resolver
from agentweft.runner import engine, prompts

NL = chr(10)


def verify_step():
    for s in runner.config("fix-with-test").steps:
        if s["role"] == "verify":
            return s
    raise AssertionError("fix-with-test has no verify step")


def declared():
    return [g for g in (verify_step().get("gates") or [])
            if g.get("gate") == "command"]


def test_the_verify_step_asks_for_the_suite_to_be_run():
    assert len(declared()) == 1
    entry = declared()[0]
    assert "pytest" in entry["command"]
    assert entry["expect"] == 0


def test_the_declaration_resolves_to_a_gate_that_shells_out():
    """through Run.gates_for, which is what the engine calls."""
    fm = runner.config("fix-with-test")
    by_role = resolver.resolve(fm.raw, runner.flow_path("fix-with-test"))
    run = runner.Run("fix-with-test", fm, by_role)
    built = [g for g in run.gates_for("verify.md") if isinstance(g, CommandGate)]
    assert len(built) == 1
    assert built[0].opts["command"] == declared()[0]["command"]
    assert int(built[0].opts.get("expect", 0)) == 0


def a_flow(tmp_path, command):
    root = tmp_path / "flows"
    d = root / "exits"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(
        "name: exits" + NL
        + "steps:" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL
        + "    gates:" + NL
        + "      - gate: command" + NL
        + "        command: " + json.dumps(command) + NL
        + "        expect: 0" + NL
        + "  - role: merge" + NL
        + "    prompt: merge.md" + NL
        + "journal: false" + NL
        + "provider:" + NL
        + "  provider: fake" + NL,
        encoding="utf-8")
    (d / "instructions.md").write_text("do the thing you are given." + NL,
                                       encoding="utf-8")
    for role in ("worker", "merge"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    return root


def go(tmp_path, monkeypatch, command):
    """run a flow whose gate is that command; -> the steps that were asked."""
    root = a_flow(tmp_path, command)
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        return "done", False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv",
                        ["run.py", "exits", "--force", "--flows", str(root)])
    monkeypatch.chdir(tmp_path)
    engine.main()
    return asked


def test_a_non_zero_exit_stops_the_run(tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch,
               [sys.executable, "-c", "raise SystemExit(1)"])
    assert asked == ["worker.md"]
    written = (tmp_path / "runs")
    gates_md = [p / "gates.md" for p in written.iterdir() if p.is_dir()]
    assert "FAIL command" in gates_md[0].read_text(encoding="utf-8")


def test_a_zero_exit_lets_the_run_carry_on(tmp_path, monkeypatch):
    asked = go(tmp_path, monkeypatch, [sys.executable, "-c", "pass"])
    assert asked == ["worker.md", "merge.md"]
