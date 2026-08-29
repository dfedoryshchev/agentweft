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


def test_every_phase_says_what_it_needs_and_what_done_looks_like():
    wf = workflow.load()
    assert wf.uncriteried() == [], [p.name for p in wf.uncriteried()]


def test_entry_and_exit_are_not_the_same_thing_as_produces():
    tests = workflow.load().phase("tests")
    assert tests.produces == "every test the feature needs, all of them failing"
    assert tests.entry == "the acceptance section of the doc is final"
    assert tests.exit == "every acceptance line has a test, and every new test fails"


def test_a_phase_with_no_criteria_reads_as_empty_not_as_an_error():
    bare = workflow.Phase({"name": "x"})
    assert bare.entry == ""
    assert bare.exit == ""
    assert workflow.Workflow({"phases": [{"name": "x"}]}).uncriteried()[0].name == "x"


def named(raw):
    """the agent name out of either node shape, without parsing it."""
    return raw["agent"] if isinstance(raw, dict) else raw


def test_a_phase_keeps_its_agents_in_the_order_the_file_gives_them():
    wf = workflow.load()
    for phase in wf.phases:
        assert [a.name for a in phase.agents] == \
            [named(a) for a in phase.raw.get("agents") or []], phase.name


def test_the_seats_in_a_review_read_in_the_order_the_file_seats_them():
    seats = workflow.load().phase("technical review").agents
    assert [str(a) for a in seats] == [
        "requirements-qa",
        "code-reviewer (refactor-advocate)",
        "code-reviewer (minimalist)",
        "architect",
    ]


def test_a_mapping_and_a_plain_string_share_one_order():
    """planning writes two seats as mappings and the third as a bare string.

    a seat's place is where it is in the file, not which of the two shapes it
    was written in.
    """
    planning = workflow.load().phase("planning")
    assert [isinstance(a, dict) for a in planning.raw["agents"]] == \
        [True, True, False]
    assert [str(a) for a in planning.agents] == [
        "code-reviewer (refactor-advocate)",
        "code-reviewer (minimalist)",
        "architect",
    ]


def test_the_distinct_agents_are_in_first_seen_order_not_sorted():
    names = workflow.load().agents()
    assert names[:5] == ["doc-researcher", "business-analyst", "product-qa",
                         "code-reviewer", "architect"]
    assert names != sorted(names)


def test_an_agent_asked_for_twice_keeps_the_place_the_first_phase_gave_it():
    # product-qa is in four phases and stays where research put it
    assert workflow.load().agents().index("product-qa") == 2
    wf = workflow.Workflow({"phases": [
        {"name": "one", "agents": ["b", "a"]},
        {"name": "two", "agents": ["a", "c"]},
    ]})
    assert wf.agents() == ["b", "a", "c"]
