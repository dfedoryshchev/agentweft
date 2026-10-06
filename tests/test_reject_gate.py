import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import gates
from agentweft.orchestrate import workflow
from agentweft.runner import engine, prompts, resume, state

RULES = [
    "business logic in an endpoint",
    {"rule": "a debugger left in", "pattern": r"breakpoint\(\)|pdb\.set_trace"},
    {"rule": "a skipped test", "pattern": r"^\s*@pytest\.mark\.skip"},
]


def place(tmp_path, monkeypatch, rules=None, project=True):
    """a project.yml beside a workflow in tmp_path/orchestrate."""
    home = tmp_path / "orchestrate"
    home.mkdir()
    monkeypatch.setattr(workflow, "ROOT", [str(home)])
    if project:
        text = "project:\n  name: here\n"
        if rules is not None:
            text += "standards:\n  immediate_reject: " + json.dumps(rules) + "\n"
        (home / "project.yml").write_text(text, encoding="utf-8")
    return tmp_path


def gate(**opts):
    return gates.build(dict({"gate": "reject"}, **opts))


def test_output_that_hits_a_rule_fails_and_names_the_rule(tmp_path, monkeypatch):
    place(tmp_path, monkeypatch, RULES)
    r = gate().run("def handler():\n    breakpoint()\n    return 1\n")
    assert not r
    assert r.detail == "rejected: a debugger left in"


def test_every_rule_it_hits_is_named(tmp_path, monkeypatch):
    place(tmp_path, monkeypatch, RULES)
    r = gate().run("@pytest.mark.skip\ndef test_x():\n    pdb.set_trace()\n")
    assert not r
    assert r.detail == "rejected: a debugger left in; a skipped test"


def test_clean_output_passes_and_says_what_was_only_asked_for(tmp_path,
                                                              monkeypatch):
    place(tmp_path, monkeypatch, RULES)
    r = gate().run("def handler():\n    return 1\n")
    assert r
    assert r.detail == "2 rules checked, 1 only asked for"


def test_a_pattern_is_per_line_like_the_regex_gate(tmp_path, monkeypatch):
    place(tmp_path, monkeypatch, RULES)
    assert not gate().run("x = 1\n    @pytest.mark.skip\n")


def test_the_rules_are_the_project_file_and_not_the_flow(tmp_path, monkeypatch):
    place(tmp_path, monkeypatch, RULES)
    assert not gate().run("breakpoint()")
    (tmp_path / "orchestrate" / "project.yml").write_text(
        "project:\n  name: here\nstandards:\n  immediate_reject: "
        + json.dumps(RULES[2:]) + "\n", encoding="utf-8")
    assert gate().run("breakpoint()")


def test_a_pattern_written_in_the_flow_is_refused(tmp_path, monkeypatch):
    place(tmp_path, monkeypatch, RULES)
    r = gate(pattern="TODO").run("x")
    assert not r
    assert "project.yml" in r.detail


def test_no_project_file_is_a_failure_not_a_pass(tmp_path, monkeypatch):
    place(tmp_path, monkeypatch, project=False)
    r = gate().run("x")
    assert not r
    assert r.detail.startswith("no project.yml")


def test_rules_that_are_all_prose_check_nothing_and_fail(tmp_path, monkeypatch):
    """a gate that checked nothing and passed would read as a rule that held."""
    place(tmp_path, monkeypatch, ["business logic in an endpoint"])
    r = gate().run("x")
    assert not r
    assert r.detail == ("no immediate_reject rule in project.yml has a "
                        "pattern, so nothing can be checked")


def test_a_broken_project_file_fails_with_the_loaders_words(tmp_path, monkeypatch):
    place(tmp_path, monkeypatch, [{"rule": "x", "pattern": "("}])
    r = gate().run("x")
    assert not r
    assert "standards: immediate_reject: x: pattern does not compile" in r.detail


def test_a_project_file_with_a_key_twice_fails(tmp_path, monkeypatch):
    place(tmp_path, monkeypatch, RULES)
    (tmp_path / "orchestrate" / "project.yml").write_text(
        "project:\n  name: here\nproject:\n  name: there\n", encoding="utf-8")
    r = gate().run("x")
    assert not r
    assert r.detail.startswith("project.yml: ")


def a_run(tmp_path, monkeypatch, reply):
    """a step whose output is a patch, held to the project's reject rules."""
    place(tmp_path, monkeypatch, RULES)
    flow = tmp_path / "flows" / "rejecting"
    flow.mkdir(parents=True)
    (flow / "worker.md").write_text("you are the worker.\n", encoding="utf-8")
    (flow / "instructions.md").write_text("one step.\n", encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: rejecting\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        "    gates:\n"
        "      - gate: reject\n"
        "journal: false\n"
        "provider:\n"
        "  provider: fake\n"
        "  reply: " + json.dumps(reply) + "\n",
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(engine, "CACHE", {})
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "rejecting", "--force"])
    engine.main()
    return "".join((p / "gates.md").read_text(encoding="utf-8")
                   for p in (tmp_path / "runs").iterdir()
                   if (p / "gates.md").exists())


def test_a_run_whose_patch_hits_a_rule_fails_the_gate(tmp_path, monkeypatch):
    out = a_run(tmp_path, monkeypatch, "+    breakpoint()\n")
    assert "FAIL reject - rejected: a debugger left in" in out


def test_a_clean_run_passes_the_gate(tmp_path, monkeypatch):
    out = a_run(tmp_path, monkeypatch, "+    return 1\n")
    assert "PASS reject - 2 rules checked, 1 only asked for" in out


def test_the_gate_is_registered():
    assert "reject" in gates.registry
    with pytest.raises(ValueError):
        gates.build({"gate": "reject-typo"})
