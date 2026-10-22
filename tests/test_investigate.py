"""`investigate:` puts a step before the fix that finds the cause and what it
reaches, and hands that to the steps after it.

`off` is the flow as it was. `cause` and `plan` are run here on the shipped
fix-with-test, copied with the key turned on, on fake answers and a real pytest.
"""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import spec
from agentweft.providers import cli_provider, fake_provider
from agentweft.roles import resolver
from agentweft.runner import engine, prompts, resume, state

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"
NODE = "tests/test_calc.py::test_add"
BROKEN = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return sum((a, b))" + NL
TEST = ("from calc import add" + NL + NL + NL
        + "def test_add():" + NL + "    assert add(1, 2) == 3" + NL)
SITE_ONE = "- calc.py:add - it subtracts where it should add"
SITE_TWO = "- calc.py:total - it calls the same subtraction"
RELATED = "- report.py:header - the header row is printed twice"
FOUND = NL.join([
    "CAUSE: calc.py:2 add returns a - b, so every sum is a difference",
    "SITES:", SITE_ONE, SITE_TWO,
    "FEEDS:", "- python calc.py total",
    "RELATED:", RELATED,
    "ROOTED: yes",
    "RULED OUT:", "- the argument parser - add(1, 2) is called with ints",
    "REPRO: python -c \"from calc import add; print(add(1, 2))\"",
    "", "```python", "def add(a, b):", "    return a - b", "```", ""])
UNROOTED = FOUND.replace(
    "ROOTED: yes", "ROOTED: no, cannot tell whether a caller relies on it")
WORKER = "FAILS: assert -1 == 3" + NL + "TEST: " + NODE + NL
PATCHER = "TEST: " + NODE + NL + "return a + b"
VERIFIED = NL.join(["PASS the test is written before the patch",
                    "PASS the test fails on the unpatched code",
                    "PASS the patch is the smallest thing that turns it green"])
RETRO = "retro.md"
# the shipped flow looks back after every run that ends, once, last
ANSWERS = {"investigator.md": FOUND, "worker.md": WORKER,
           "patcher.md": PATCHER, "verify.md": VERIFIED,
           RETRO: fake_provider.NOTHING_TO_KEEP}


def raw(**extra):
    out = {"name": "x", "steps": [{"role": "worker", "prompt": "worker.md"}]}
    out.update(extra)
    return out


def test_the_key_is_absent_and_the_steps_are_the_flows_own():
    assert [s["role"] for s in spec.load(raw()).steps] == ["worker"]


@pytest.mark.parametrize("value", ["off", False])
def test_off_leaves_the_steps_as_they_are(value):
    # yaml reads a bare `off` as false
    assert [s["role"] for s in spec.load(raw(investigate=value)).steps] \
        == ["worker"]


@pytest.mark.parametrize("mode", ["cause", "plan"])
def test_on_puts_a_read_only_investigator_first(mode):
    steps = spec.load(raw(investigate=mode)).steps
    assert [s["role"] for s in steps] == ["investigator", "worker"]
    first = steps[0]
    assert first["must_produce"] == "CAUSE:"
    assert [g["gate"] for g in first["gates"]] == ["regex", "regex"]
    assert "write" not in first["tools"] and "edit" not in first["tools"]


@pytest.mark.parametrize("value", ["yes", True, "planner", 3])
def test_any_other_value_is_refused(value):
    with pytest.raises(ValueError) as e:
        spec.load(raw(investigate=value))
    assert "investigate should be one of off, cause, plan" in str(e.value)


def test_the_investigator_takes_a_tier_like_any_role():
    spec.load(raw(investigate="cause", tiers={"investigator": "low"}))


def test_the_sites_gate_wants_a_file_and_a_function():
    from agentweft.guardrails import gates

    step = spec.load(raw(investigate="cause")).steps[0]
    gate = gates.build(step["gates"][0])
    assert gate.run(FOUND).ok
    assert not gate.run(FOUND.replace(SITE_ONE + NL + SITE_TWO,
                                      "- somewhere in calc")).ok
    assert not gate.run("CAUSE: calc.py:2" + NL).ok


def test_the_library_has_words_for_the_role_and_it_is_not_the_planner():
    assert "investigator" in resolver.library_roles()
    words = resolver.role_prompt("investigator.md")
    for label in ("CAUSE:", "SITES:", "FEEDS:", "RELATED:", "ROOTED:",
                  "RULED OUT:", "REPRO:"):
        assert label in words, label


def test_the_shipped_flow_says_off():
    fm = runner.config("fix-with-test")
    assert fm.get("investigate") in ("off", False)
    assert [s["role"] for s in fm.steps] == ["worker", "patcher"]


def flow_with(tmp_path, mode):
    root = tmp_path / "flows"
    shutil.copytree(FLOWS / "fix-with-test", root / "fix-with-test",
                    dirs_exist_ok=True)
    yaml = root / "fix-with-test" / "flow.yaml"
    lines = [l for l in yaml.read_text(encoding="utf-8").split(NL)
             if not l.startswith("investigate:")]
    lines.insert(1, "investigate: " + mode)
    yaml.write_text(NL.join(lines), encoding="utf-8")
    return root


def run_it(tmp_path, monkeypatch, answers, mode="cause", fixes=True,
           more=(), tests=()):
    flows = flow_with(tmp_path, mode)
    project = tmp_path / "project"
    if not project.exists():
        (project / "tests").mkdir(parents=True)
        (project / "conftest.py").write_text("", encoding="utf-8")
        (project / "calc.py").write_text(BROKEN, encoding="utf-8")
    asked = []
    written = list(tests)

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        if step == "worker.md":
            (project / "tests" / "test_calc.py").write_text(
                written.pop(0) if written else TEST, encoding="utf-8")
        if step == "patcher.md" and fixes:
            (project / "calc.py").write_text(FIXED, encoding="utf-8")
        return answers.get(step, ""), False

    monkeypatch.setattr(engine, "call", fake_call)
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
                                      "--task", "add(1, 2) returns -1"]
                        + list(more))
    code = engine.main()
    return code, asked


def prompt_of(asked, step):
    return [p for s, p in asked if s == step][-1]


def journal(tmp_path):
    return (tmp_path / "runs" / "journal.md").read_text(encoding="utf-8")


def test_an_investigator_with_no_cause_line_stops_the_run_there(
        tmp_path, monkeypatch):
    answer = FOUND.replace("CAUSE: ", "the cause is ")
    code, asked = run_it(tmp_path, monkeypatch, dict(ANSWERS, **{
        "investigator.md": answer}))
    assert [s for s, _ in asked] == ["investigator.md", RETRO]
    assert code == 2
    assert "  failed at investigator.md  " in journal(tmp_path)


def test_an_investigator_naming_no_site_stops_the_run_there(tmp_path,
                                                            monkeypatch):
    answer = FOUND.replace(SITE_ONE + NL + SITE_TWO, "- somewhere in calc")
    code, asked = run_it(tmp_path, monkeypatch, dict(ANSWERS, **{
        "investigator.md": answer}))
    assert [s for s, _ in asked] == ["investigator.md", "investigator.md",
                                     RETRO]
    assert "  failed at investigator.md  " in journal(tmp_path)


def test_an_investigator_that_says_nothing_about_rooted_stops_the_run_there(
        tmp_path, monkeypatch):
    answer = FOUND.replace("ROOTED: yes" + NL, "")
    code, asked = run_it(tmp_path, monkeypatch, dict(ANSWERS, **{
        "investigator.md": answer}))
    assert [s for s, _ in asked] == ["investigator.md", "investigator.md",
                                     RETRO]
    assert "  failed at investigator.md  " in journal(tmp_path)


def test_the_investigator_is_given_the_task_and_told_to_change_nothing(
        tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS)
    told = prompt_of(asked, "investigator.md")
    assert "add(1, 2) returns -1" in told
    assert "{TASK}" not in told
    assert "TESTS:" not in told


def test_a_two_site_cause_reaches_the_worker_as_anchors_not_code(
        tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS)
    assert code == 0
    assert [s for s, _ in asked] == ["investigator.md", "worker.md",
                                     "patcher.md", RETRO]
    told = prompt_of(asked, "worker.md")
    assert SITE_ONE in told and SITE_TWO in told
    assert "CAUSE: calc.py:2" in told
    assert "- the argument parser - add(1, 2) is called with ints" in told
    assert "REPRO: python -c" in told
    assert "def add(a, b):" not in told
    assert "```python" not in told


def test_the_patcher_is_told_to_fix_every_named_site(tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS)
    told = prompt_of(asked, "patcher.md")
    assert SITE_ONE in told and SITE_TWO in told
    assert "NOT REACHED:" in told
    assert "anything the test does not reach" not in told
    assert "{SCOPE}" not in told


def test_related_defects_go_to_the_output_and_not_to_the_fix(tmp_path,
                                                             monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS)
    for step in ("worker.md", "patcher.md"):
        assert "header row is printed twice" not in prompt_of(asked, step)
    saved = [p for p in (tmp_path / "runs").iterdir()
             if p.is_file() and p.name.startswith("fix-with-test-")]
    assert len(saved) == 1
    text = saved[0].read_text(encoding="utf-8")
    assert RELATED in text
    assert text.startswith(PATCHER)


def test_an_unrooted_cause_parks_with_the_gap_named(tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, dict(ANSWERS, **{
        "investigator.md": UNROOTED}))
    assert [s for s, _ in asked] == ["investigator.md"]
    assert code == 2
    said = journal(tmp_path)
    assert "  parked at investigator.md  " in said
    assert "cannot tell whether a caller relies on it" in said
    folder = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    assert (folder / "handoff.md").exists()


def test_a_resumed_park_hands_the_worker_the_sites(tmp_path, monkeypatch):
    run_it(tmp_path, monkeypatch, dict(ANSWERS, **{
        "investigator.md": UNROOTED}))
    parked = [p.name for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS,
                         more=["--resume", parked])
    assert code == 0
    assert [s for s, _ in asked] == ["worker.md", "patcher.md", RETRO]
    assert SITE_TWO in prompt_of(asked, "worker.md")
    assert SITE_TWO in prompt_of(asked, "patcher.md")


def test_plan_asks_for_the_tests_and_the_decisions_as_well(tmp_path,
                                                           monkeypatch):
    planned = FOUND + NL.join([
        "TESTS:", "- python calc.py total - 1 2 prints 3",
        "DECISIONS:", "- whether total keeps its old name", ""])
    code, asked = run_it(tmp_path, monkeypatch, dict(ANSWERS, **{
        "investigator.md": planned}), mode="plan")
    assert code == 0
    told = prompt_of(asked, "investigator.md")
    assert "TESTS:" in told and "DECISIONS:" in told
    assert "- python calc.py total - 1 2 prints 3" in prompt_of(asked,
                                                                "worker.md")
    saved = [p for p in (tmp_path / "runs").iterdir()
             if p.is_file() and p.name.startswith("fix-with-test-")][0]
    assert "- whether total keeps its old name" in saved.read_text(
        encoding="utf-8")


def test_off_sends_the_patcher_the_words_it_always_had(tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS, mode="off")
    assert [s for s, _ in asked] == ["worker.md", "patcher.md", RETRO]
    told = prompt_of(asked, "patcher.md")
    assert "- do not touch anything the test does not reach" + NL in told
    assert "{SCOPE}" not in told
    assert "NOT REACHED" not in told
    assert "investigator" not in prompt_of(asked, "worker.md")


GREEN = TEST.replace("== 3", "== -1")
TWO_CAUSES = WORKER + NL.join([
    "", "HANDOFF", "DID:",
    "- the cause is add returning a - b",
    "- a second cause is total calling add with its arguments swapped",
    "END HANDOFF", ""])


def decided(tmp_path):
    folder = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]
    path = folder / "decisions.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_auto_is_a_mode_the_flow_file_takes():
    assert spec.check(raw(investigate="auto")) == []
    steps = spec.load(raw(investigate="auto")).steps
    assert [s["role"] for s in steps] == ["investigator", "worker"]


def test_auto_never_calls_the_cause_step_on_a_clean_run(tmp_path,
                                                         monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS, mode="auto")
    assert code == 0
    assert [s for s, _ in asked] == ["worker.md", "patcher.md", RETRO]
    assert "the cause step was switched on" not in decided(tmp_path)


def test_auto_switches_the_cause_step_on_when_the_red_test_fails_twice(
        tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS, mode="auto",
                         tests=[GREEN, GREEN])
    assert code == 0
    assert [s for s, _ in asked] == ["worker.md", "worker.md",
                                     "investigator.md", "worker.md",
                                     "patcher.md", RETRO]
    assert SITE_TWO in prompt_of(asked, "worker.md")
    said = decided(tmp_path)
    assert "the cause step was switched on" in said
    assert "red-test" in said


def test_auto_switches_the_cause_step_on_when_did_names_two_causes(
        tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, dict(ANSWERS, **{
        "worker.md": TWO_CAUSES}), mode="auto")
    assert code == 0
    assert [s for s, _ in asked] == ["worker.md", "investigator.md",
                                     "worker.md", "patcher.md", RETRO]
    assert "CAUSE: calc.py:2" in prompt_of(asked, "worker.md")
    said = decided(tmp_path)
    assert "the cause step was switched on" in said
    assert "a second cause is total" in said


def test_auto_switches_on_once_and_a_third_red_failure_stops_the_run(
        tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS, mode="auto",
                         tests=[GREEN, GREEN, GREEN])
    assert [s for s, _ in asked] == ["worker.md", "worker.md",
                                     "investigator.md", "worker.md", RETRO]
    assert code != 0
    assert "  failed at worker.md  " in journal(tmp_path)


def test_cause_still_runs_the_step_first_and_a_red_failure_stops_as_before(
        tmp_path, monkeypatch):
    code, asked = run_it(tmp_path, monkeypatch, ANSWERS, mode="cause",
                         tests=[GREEN, GREEN])
    assert [s for s, _ in asked] == ["investigator.md", "worker.md",
                                     "worker.md", RETRO]
    assert code != 0
