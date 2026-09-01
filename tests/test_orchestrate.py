import sys

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.flow import spec
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


def test_a_phase_is_a_flow_spec():
    """the whole row. every phase goes through the flow loader and passes it."""
    for phase in workflow.load().phases:
        assert isinstance(phase.spec, spec.FlowSpec), phase.name
        assert spec.check(workflow.as_flow(phase.raw)) == [], phase.name


def test_the_seats_are_the_steps():
    for phase in workflow.load().phases:
        assert [s["role"] for s in phase.spec.steps] == \
            [a.name for a in phase.agents], phase.name


def test_a_phase_that_stops_pauses_on_its_last_step():
    """`gate: user` is a flow word now, and the word is `pause`.

    it goes on the last step because a phase stops after its jobs are done,
    and it is not spelled `gate` there because `gate` on a step is a program.
    """
    for name in ("planning", "delivery"):
        steps = workflow.load().phase(name).spec.steps
        assert steps[-1]["pause"] == "user", name
        assert [s for s in steps[:-1] if s.get("pause")] == [], name


def test_a_phase_that_does_not_stop_has_no_pause_anywhere():
    for phase in workflow.load().phases:
        if not phase.gate:
            assert [s for s in phase.spec.steps if s.get("pause")] == [], phase.name


def test_the_criteria_are_promises_now():
    tests = workflow.load().phase("tests")
    assert tests.spec.promises.inputs == tests.entry
    assert tests.spec.promises.outputs == tests.produces
    assert tests.spec.promises.invariants == [tests.exit]


def test_an_exit_line_became_an_invariant_and_is_still_not_checked():
    """the merge made them one vocabulary. it did not make them checkable.

    the checker knows three shapes and no exit line in the file is any of
    them, so this says none of them can be checked rather than pretending the
    translation bought something it did not.
    """
    from agentweft.guardrails import promises

    lines = [p.exit for p in workflow.load().phases if p.exit]
    assert len(lines) == 8
    assert [ok for _, ok, _ in promises.check("", lines)] == [None] * 8


def test_the_stance_does_not_reach_the_step():
    planning = workflow.load().phase("planning")
    assert [a.personality for a in planning.agents] == \
        ["refactor-advocate", "minimalist", ""]
    assert [sorted(s) for s in planning.spec.steps] == \
        [["role"], ["role"], ["pause", "role"]]


def test_nothing_in_the_file_arrives_unplaced():
    assert workflow.unplaced() == []


def test_a_new_phase_key_is_unplaced_until_it_is_translated_or_named():
    wf = workflow.Workflow({"name": "x", "lead": "lead",
                            "phases": [{"name": "p", "cadence": "weekly"}]})
    assert workflow.unplaced(wf) == ["phase.cadence"]


def test_what_did_not_translate_is_named_and_says_why():
    words = workflow.terms()
    translated = [phase for phase, _ in workflow.TRANSLATION]
    for miss in workflow.RESIDUE:
        assert miss.why.strip()
        for term in miss.terms:
            assert term in words, term
            assert term not in translated, term


def test_the_same_reader_refuses_a_duplicate_key(tmp_path):
    """safe_load keeps the LAST of two identical keys and says nothing.

    the flow file has been read by a loader that refuses them for months;
    this one was read by safe_load until both files started sharing a reader,
    so a phase with two `agents:` blocks quietly lost one of them.
    """
    path = tmp_path / "workflow.yaml"
    path.write_text("name: x\nlead: lead\nphases:\n  - name: p\n"
                    "    agents: [a]\n    agents: [b]\n", encoding="utf-8")
    assert yaml.safe_load(path.read_text())["phases"][0]["agents"] == ["b"]
    with pytest.raises(yaml.YAMLError):
        workflow.load(path)
