import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import workflow


def test_the_workflow_loads():
    wf = workflow.load()
    assert wf.name
    assert wf.lead
    assert len(wf.phases) > 1


def test_the_phases_keep_the_order_the_file_gives_them():
    wf = workflow.load()
    names = [p.name for p in wf.phases]
    assert names == [p["name"] for p in wf.raw["phases"]]


def test_every_named_agent_has_a_prompt_file():
    wf = workflow.load()
    for phase in wf.phases:
        for agent in phase.agents:
            assert agent.prompt().exists(), (phase.name, agent.name)


def test_the_lead_has_one_too_and_is_not_an_agent():
    wf = workflow.load()
    assert (workflow.root() / (wf.lead + ".md")).exists()
    assert wf.lead not in wf.agents()


def test_it_stops_twice():
    wf = workflow.load()
    assert [p.name for p in wf.gates()] == ["planning", "delivery"]
    assert all(p.gate == "user" for p in wf.gates())


def test_the_same_agent_can_be_launched_twice_with_different_personalities():
    seats = workflow.load().phase("planning").agents
    reviewers = [a for a in seats if a.name == "code-reviewer"]
    assert len(reviewers) == 2
    assert sorted(a.personality for a in reviewers) == \
        ["minimalist", "refactor-advocate"]
    assert str(reviewers[0]).endswith("(refactor-advocate)")


def test_a_plain_string_is_an_agent_with_no_personality():
    only = workflow.load().phase("implementation").agents
    assert [a.name for a in only] == ["developer"]
    assert only[0].personality == ""
    assert str(only[0]) == "developer"


def test_a_phase_that_does_not_loop_reads_as_one_pass():
    wf = workflow.load()
    assert wf.phase("implementation").loop == 1
    assert wf.phase("technical review").loop == 5
