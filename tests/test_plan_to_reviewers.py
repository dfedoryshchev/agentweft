"""the reviewers are handed the plan's behaviours and check the code against
them.

the lead's plan reached only the step that writes the tests. a behaviour the
plan listed and the tests dropped was caught only when a reviewer derived it
again from the spec. both reviewers of the shipped build-feature flow are now
handed the plan's `- behaviour:` lines, as the lead wrote them, under the
spec: each planned behaviour has code and a test that checks it. a flow
whose lead runs no step of it has no plan, and says so; a plan with no
behaviour line says so, never an empty section read as all covered.
"""
import sys

sys.path.insert(0, ".")
from agentweft.runner import prompts

from test_build_feature_flow import ALL, PLAN, run_it

NL = chr(10)
SECOND = ("- behaviour: mul(-2, 3) is -6" + NL + "  file: calc.py" + NL
          + "  spec: nothing in the spec" + NL)


def reviewer_prompts(tmp_path, monkeypatch, plan):
    answers = dict(ALL, **{"planner.md": [plan]})
    asked, _, sent, code = run_it(tmp_path, monkeypatch, answers)
    assert code == 0
    return dict((step, prompt) for step, prompt in zip(asked, sent)
                if step.startswith("reviewer"))


def test_both_reviewers_are_handed_the_plan_s_behaviour_lines(tmp_path,
                                                             monkeypatch):
    plan = "the plan, in short." + NL + NL + PLAN + SECOND + NL \
        + "HANDOFF" + NL + "DID:" + NL + "- planned it" + NL + "END HANDOFF"
    found = reviewer_prompts(tmp_path, monkeypatch, plan)
    assert set(found) == {"reviewer.md", "reviewer-runs.md"}
    for step, prompt in found.items():
        assert prompts.PLAN not in prompt, step
        for line in (PLAN + SECOND).strip().split(NL):
            assert prompt.count(line) >= 1, (step, line)
        assert "the plan, in short." not in prompt.split(
            "the plan the run's lead set out")[1].split("each planned")[0]


def test_a_plan_with_no_behaviour_line_says_so(tmp_path, monkeypatch):
    found = reviewer_prompts(tmp_path, monkeypatch, "nothing planned" + NL)
    for prompt in found.values():
        assert prompts.NO_BEHAVIOURS in prompt


def test_the_plan_is_read_off_the_lead_s_answer_and_nothing_else():
    text = "x " + prompts.PLAN + " y"
    assert prompts.plan_of("no placeholder", PLAN, True) == {}
    assert prompts.plan_of(text, None, False) == {
        prompts.PLAN: prompts.NO_PLAN_STEP}
    assert prompts.plan_of(text, "", True) == {
        prompts.PLAN: prompts.NO_BEHAVIOURS}
    said = prompts.plan_of(text, "intro" + NL + PLAN + "after" + NL, True)
    assert said == {prompts.PLAN: PLAN.rstrip(NL)}
    win = "- behaviour: le caf" + chr(0xe9) + NL + "  file: app\\x.py" + NL
    assert prompts.plan_of(text, win, True) == {prompts.PLAN: win.rstrip(NL)}
    fenced = "```" + NL + PLAN + "```" + NL
    assert prompts.plan_of(text, fenced, True) == {
        prompts.PLAN: prompts.NO_BEHAVIOURS}
