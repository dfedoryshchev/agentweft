import os
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.roles import resolver


def test_env_keys_are_substituted(monkeypatch):
    monkeypatch.setenv("INBOX", "C:/somewhere")
    assert runner.load_prompt.__module__
    from agentweft.runner import prompts
    assert prompts.substitute("read {INBOX} now") == "read C:/somewhere now"


def test_an_unknown_brace_is_left_alone():
    from agentweft.runner import prompts
    assert prompts.substitute("keep {THIS}") == "keep {THIS}"


def test_every_role_gets_the_shared_fragments():
    cfg = runner.config("weekly-digest")
    by_role = resolver.resolve(cfg.raw, runner.flow_path("weekly-digest"))
    for role, rules in by_role.items():
        assert "markdown only" in rules
        assert "never invent a number" in rules


def _composed(flow):
    from agentweft.runner import prompts
    cfg = runner.config(flow)
    by_role = resolver.resolve(cfg.raw, runner.flow_path(flow), cfg.promises.as_prompt())
    return {step["role"]: prompts.load_prompt(flow, step["prompt"], by_role[step["role"]],
                                              step["role"])
            for step in cfg.raw["steps"]}


def test_a_reviewer_keeps_what_it_is_unsure_of_and_marks_it():
    reviewer = _composed("code-review")["reviewer"]
    assert "leave it out" not in reviewer
    assert "mark it unsure" in reviewer
    assert "do not drop it" in reviewer


def test_a_worker_is_still_told_never_to_invent():
    worker = _composed("code-review")["worker"]
    assert "never invent a number, a name or a date" in worker
    assert "leave it out" not in worker


def _reviewer_flows():
    import pathlib
    out = []
    for folder in sorted(pathlib.Path("flows").iterdir()):
        if folder.name.startswith("_") or not (folder / "flow.yaml").is_file():
            continue
        if any(s["role"] == "reviewer" for s in runner.config(folder.name).raw["steps"]):
            out.append(folder.name)
    return out


def test_every_reviewer_is_asked_to_run_what_it_suspects():
    from agentweft.runner.config import asks_for_verdict
    flows = _reviewer_flows()
    assert "code-review" in flows
    for flow in flows:
        reviewer = _composed(flow)["reviewer"]
        assert "run it" in reviewer, flow
        assert "the command you ran and what it printed" in reviewer, flow
        assert "under each finding" in reviewer, flow
        assert asks_for_verdict(reviewer), flow


def test_a_finding_with_no_command_is_kept_and_marked_unsure():
    for flow in _reviewer_flows():
        reviewer = _composed(flow)["reviewer"]
        assert "a finding you could not run stays in, marked unsure" in reviewer, flow


def test_a_code_reviewer_tries_the_inputs_the_tests_do_not():
    reviewer = _composed("code-review")["reviewer"]
    for said in ("for each changed function",
                 "very large and very small numbers",
                 "empty and very long text",
                 "non-ASCII text written to a file and to a pipe",
                 "a missing or malformed file"):
        assert said in reviewer, said


def test_only_the_judging_roles_get_the_extra_block():
    cfg = runner.config("weekly-digest")
    by_role = resolver.resolve(cfg.raw, runner.flow_path("weekly-digest"))
    assert "allowed to say the work is wrong" in by_role["reviewer"]
    assert "allowed to say the work is wrong" not in by_role["planner"]
