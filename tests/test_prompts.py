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


def test_what_goes_into_one_placeholder_is_never_read_for_another():
    from agentweft.runner import prompts
    values = {prompts.MARK: "fix {BRIEF}", prompts.BRIEF: "quoted {TASK}",
              prompts.SPEC_AT_START: "spec says {SPEC_DIFF} and {TASK}",
              prompts.SPEC_DIFF: "moved {SPEC_AT_START}"}
    text = "{TASK} / {BRIEF} / {SPEC_AT_START} / {SPEC_DIFF} / {TASK}"
    assert prompts.fill(text, values) == (
        "fix {BRIEF} / quoted {TASK} / spec says {SPEC_DIFF} and {TASK}"
        " / moved {SPEC_AT_START} / fix {BRIEF}")
    assert prompts.fill("keep {THIS}", values) == "keep {THIS}"
    assert prompts.fill("{TASK}", {}) == "{TASK}"


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


def _prompt_files():
    """-> {posix path: its words on one line} for every file a shipped
    flow's step can be sent: the flows' own, the role library, the
    fragments and the skills."""
    import pathlib
    import re
    found = sorted(pathlib.Path("flows").glob("*/*.md")) \
        + sorted(pathlib.Path("agentweft/roles/library").glob("*.md")) \
        + sorted(pathlib.Path("agentweft/fragments").glob("*.md")) \
        + sorted(pathlib.Path("agentweft/skills").glob("*/SKILL.md"))
    return {p.as_posix(): re.sub(r"\s+", " ", p.read_text(encoding="utf-8"))
            for p in found if not p.parts[1].startswith("_")}


# each said what a gate already holds, a gate with a test that shows it
# firing on the shipped flows; the gate's own refusal is what tells the step
GATE_HELD = (
    "a quote that is not there fails your answer",
    "a file that is not there or does not fail stops the run",
    "VERIFIED carries the run that showed",
    "is reported as pinning current behaviour",
    "never counted as coverage",
    "a suite that does, stops the run",
    "a suite that does not pass stops the run",
    "this is the flow, not a preference",
    "that is a failed run, not a shortcut",
    "the run stops before any test is written",
    "the same question in a doubt is printed once anyway",
    "a claim it does not show is printed as such",
    "a spec line removed or rewritten that no ruling in decisions.md quotes",
)


def test_no_prompt_tells_a_step_what_a_gate_already_holds():
    files = _prompt_files()
    assert "agentweft/roles/library/reviewer.md" in files
    assert "flows/fix-with-test/worker.md" in files
    said = [(path, line) for path, text in files.items() for line in GATE_HELD
            if line in text]
    assert said == []


def test_a_shared_line_reaches_each_shipped_step_once():
    for flow in ("fix-with-test", "build-feature"):
        for role, prompt in _composed(flow).items():
            for line in ("no preamble, no closing paragraph",
                         "never invent a number, a name or a date"):
                assert prompt.count(line) == 1, (flow, role, line)


def test_the_suite_rule_stays_where_its_refusal_says_too_little():
    import re
    patcher = re.sub(r"\s+", " ", _composed("fix-with-test")["patcher"])
    worker = re.sub(r"\s+", " ", _composed("build-feature")["worker"])
    assert "the whole suite has to pass with it, not only this test" in patcher
    assert "the whole suite has to pass with your code" in worker


def test_only_the_judging_roles_get_the_extra_block():
    cfg = runner.config("weekly-digest")
    by_role = resolver.resolve(cfg.raw, runner.flow_path("weekly-digest"))
    assert "allowed to say the work is wrong" in by_role["reviewer"]
    assert "allowed to say the work is wrong" not in by_role["planner"]


def test_every_rule_of_a_skill_list_starts_a_line_of_its_own():
    import pathlib
    import re
    for path in sorted(pathlib.Path("agentweft/skills").glob("*/SKILL.md")):
        for line in path.read_text(encoding="utf-8").split("\n"):
            assert not re.search(r"\w- [a-z]", line[2:]), (path, line[:80])
