import json
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.guardrails import gates
from agentweft.runner import engine, prompts, resume, state

NL = chr(10)


def test_red_is_the_default_and_passes_on_a_fails_line():
    g = gates.build({"gate": "red-test"})
    r = g.run("wrote the test\nFAILS: KeyError: 'id'")
    assert r
    assert r.detail.startswith("red")


def test_red_fails_when_the_output_has_no_marker():
    g = gates.build({"gate": "red-test", "red": True})
    r = g.run("wrote the test, it fails on the old code")
    assert not r
    assert "no FAILS: line" in r.detail


def test_green_fails_when_the_marker_is_still_there():
    g = gates.build({"gate": "red-test", "red": False})
    r = g.run("patched it\nFAILS: KeyError: 'id'")
    assert not r
    assert "still there after the patch" in r.detail


def test_green_passes_once_the_marker_is_gone():
    g = gates.build({"gate": "red-test", "red": False})
    r = g.run("patched it, 1 passed")
    assert r
    assert r.detail.startswith("green")


def test_the_marker_can_be_changed():
    g = gates.build({"gate": "red-test", "marker": "RED:"})
    assert g.run("RED: AssertionError")
    assert not g.run("FAILS: AssertionError")


def test_it_is_a_substring_match_anywhere_in_the_text():
    g = gates.build({"gate": "red-test"})
    assert g.run("the old code said FAILS: before i looked")
    assert g.run("NOTFAILS: at all")
    assert not g.run("fails: lowercase")


def test_without_a_command_the_pass_says_nothing_was_run():
    g = gates.build({"gate": "red-test"})
    r = g.run("FAILS: this test was never written or run")
    assert r
    assert "nothing was run" in r.detail


RUN = [sys.executable, "{test}"]
CLAIM = "FAILS: KeyError: 'id'" + NL + "TEST: test_bug.py" + NL


def a_test(where, body, name="test_bug.py"):
    (where / name).write_text(body + NL, encoding="utf-8")


def red(where, **opts):
    return gates.build(dict({"gate": "red-test", "command": RUN}, **opts),
                       where=where)


def test_a_test_that_fails_is_red(tmp_path):
    a_test(tmp_path, "raise SystemExit(1)")
    r = red(tmp_path).run(CLAIM)
    assert r
    assert "exit 1" in r.detail


def test_a_test_that_passes_on_the_unpatched_code_is_not_red(tmp_path):
    a_test(tmp_path, "pass")
    r = red(tmp_path).run(CLAIM)
    assert not r
    assert "passed" in r.detail


def test_a_test_that_was_never_written_is_not_red(tmp_path):
    r = red(tmp_path).run(CLAIM)
    assert not r
    assert "never written" in r.detail


def test_a_claim_with_no_test_named_is_not_red(tmp_path):
    a_test(tmp_path, "raise SystemExit(1)")
    r = red(tmp_path).run("FAILS: KeyError: 'id'")
    assert not r
    assert "no TEST: line" in r.detail


def test_a_test_named_outside_the_place_is_refused(tmp_path):
    (tmp_path / "work").mkdir()
    a_test(tmp_path, "raise SystemExit(1)", "outside.py")
    r = red(tmp_path / "work").run("FAILS: x" + NL + "TEST: ../outside.py")
    assert not r
    assert "outside" in r.detail


def test_an_exit_that_is_not_a_failing_test_is_not_red(tmp_path):
    """pytest says 5 when it collected nothing and 4 when it was called
    wrong. neither is a test that ran and failed."""
    a_test(tmp_path, "raise SystemExit(5)")
    r = red(tmp_path).run(CLAIM)
    assert not r
    assert "exit 5" in r.detail


def test_expect_says_which_exit_is_a_failing_test(tmp_path):
    a_test(tmp_path, "raise SystemExit(2)")
    assert red(tmp_path, expect=2).run(CLAIM)


def test_the_claim_is_still_required_when_the_test_is_run(tmp_path):
    a_test(tmp_path, "raise SystemExit(1)")
    r = red(tmp_path).run("TEST: test_bug.py")
    assert not r
    assert "no FAILS: line" in r.detail


def test_a_missing_runner_fails_rather_than_raising(tmp_path):
    a_test(tmp_path, "raise SystemExit(1)")
    g = gates.build({"gate": "red-test",
                     "command": ["definitely-not-a-real-binary", "{test}"]},
                    where=tmp_path)
    r = g.run(CLAIM)
    assert not r
    assert "not on PATH" in r.detail


def worker_gate():
    for s in runner.config("fix-with-test").steps:
        if s["role"] == "worker":
            return [g for g in (s.get("gates") or [])
                    if g.get("gate") == "red-test"][0]
    raise AssertionError("fix-with-test has no worker step")


def test_fix_with_test_runs_the_test_it_was_told_about():
    g = worker_gate()
    assert "pytest" in g["command"]
    assert "{test}" in g["command"]


def test_fix_with_test_asks_the_worker_to_name_the_test():
    text = (runner.flow_path("fix-with-test") / "worker.md").read_text(
        encoding="utf-8")
    assert "TEST:" in text


def a_flow(tmp_path, monkeypatch, answer):
    """a red-gated worker then a merge, on a fake call, started from tmp_path."""
    flow = tmp_path / "flows" / "red-first"
    flow.mkdir(parents=True)
    (flow / "instructions.md").write_text("red first." + NL, encoding="utf-8")
    for role in ("worker", "merge"):
        (flow / (role + ".md")).write_text("you are the " + role + "." + NL,
                                           encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: red-first" + NL
        + "steps:" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL
        + "    gates:" + NL
        + "      - gate: red-test" + NL
        + "        command: " + json.dumps(RUN) + NL
        + "  - role: merge" + NL
        + "    prompt: merge.md" + NL
        + "journal: false" + NL
        + "provider:" + NL
        + "  provider: fake" + NL,
        encoding="utf-8")
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        return answer, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "red-first", "--force",
                                      "--workdir", "project"])
    return asked


def gates_md(tmp_path):
    return "".join((p / "gates.md").read_text(encoding="utf-8")
                   for p in (tmp_path / "runs").iterdir()
                   if (p / "gates.md").exists())


def test_a_run_goes_on_once_the_test_has_failed_in_its_workdir(tmp_path,
                                                                monkeypatch):
    (tmp_path / "project").mkdir()
    a_test(tmp_path / "project", "raise SystemExit(1)")
    asked = a_flow(tmp_path, monkeypatch, CLAIM)
    engine.main()
    assert "PASS red-test" in gates_md(tmp_path)
    assert asked == ["worker.md", "merge.md"]


def test_a_run_stops_when_the_test_already_passes(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir()
    a_test(tmp_path / "project", "pass")
    asked = a_flow(tmp_path, monkeypatch, CLAIM)
    engine.main()
    assert "FAIL red-test" in gates_md(tmp_path)
    assert asked == ["worker.md"]
