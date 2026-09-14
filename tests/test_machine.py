import sys

import pytest

sys.path.insert(0, ".")
from agentweft.orchestrate import machine, workflow

HAPPY = ["ok", "ok", "approve", "ok", "ok", "ok", "ok", "ok", "ok", "approve"]


def a_workflow(phases):
    return workflow.Workflow({"name": "x", "lead": "lead", "phases": phases})


def test_the_states_are_not_the_phases():
    """the whole finding, as two numbers.

    eight phases, and a run can be in fourteen situations before either of the
    two ways it ends. the gate and the loop are where the extra six come from.
    """
    m = machine.Machine()
    assert len(m.wf.phases) == 8
    assert len(m.states()) == 16
    assert [str(s) for s in m.states()][-2:] == ["done", "attention"]


def test_a_phase_that_stops_is_two_states():
    """`gate: user` is a situation, not a mark on the one before it.

    the seats are done and nothing is running; what leaves is a person, and no
    event that moves a working phase moves this one.
    """
    m = machine.Machine()
    running = machine.State("planning")
    waiting = m.step(running, machine.OK)
    assert waiting == machine.State("planning", waiting=True)
    assert str(waiting) == "planning (waiting)"
    assert m.step(waiting, machine.OK) is None
    assert m.step(waiting, machine.REDO) is None
    assert m.step(waiting, machine.APPROVE) == machine.State("feature doc")


def test_a_phase_that_does_not_stop_goes_straight_on():
    m = machine.Machine()
    assert m.step(machine.State("research"), machine.OK) == machine.State("planning")
    assert m.step(machine.State("research"), machine.APPROVE) is None


def test_which_time_round_it_is_has_to_be_in_the_state():
    """a phase with a `loop` is as many states as the count on it.

    five trips through technical review are five different situations, because
    what a refusal does depends on which one you are in.
    """
    m = machine.Machine()
    reviews = [s for s in m.states() if s.name == "technical review"]
    assert [str(s) for s in reviews] == [
        "technical review",
        "technical review #2",
        "technical review #3",
        "technical review #4",
        "technical review #5",
    ]
    assert m.wf.phase("technical review").loop == len(reviews)


def test_the_fifth_refusal_is_a_persons_problem_not_a_sixth_trip():
    """the exit line says it ran five times and became mine. this is that."""
    m = machine.Machine()
    state = machine.State("technical review")
    for trip in (2, 3, 4, 5):
        state = m.step(state, machine.REDO)
        assert state == machine.State("technical review", trip)
    assert m.step(state, machine.REDO) == machine.State(machine.ATTENTION)


def test_a_refused_phase_that_is_let_through_still_goes_on():
    m = machine.Machine()
    assert m.step(machine.State("technical review", 4), machine.OK) == \
        machine.State("product review")


def test_a_phase_with_no_loop_has_no_way_back():
    """the file says where a refusal goes exactly once, so this says it once.

    handing back None is the point: the other seven phases have no target
    written anywhere, and choosing one here would be this file deciding
    something workflow.yaml has not.
    """
    m = machine.Machine()
    assert m.step(machine.State("implementation"), machine.REDO) is None
    assert m.no_way_back() == ["research", "planning", "feature doc", "tests",
                               "implementation", "product review", "delivery"]
    assert "technical review" not in m.no_way_back()


def test_an_event_it_has_no_name_for_is_refused_out_loud():
    """a typo would otherwise read as a situation with no move out of it."""
    m = machine.Machine()
    with pytest.raises(ValueError) as e:
        m.step(m.start(), "approved")
    assert "no such event approved" in str(e.value)


def test_a_run_nobody_sends_back_walks_the_file_in_order():
    m = machine.Machine()
    seen, refused = m.walk(HAPPY)
    assert refused is None
    assert [str(s) for s in seen] == [
        "research",
        "planning",
        "planning (waiting)",
        "feature doc",
        "tests",
        "implementation",
        "technical review",
        "product review",
        "delivery",
        "delivery (waiting)",
        "done",
    ]
    assert [p.name for p in m.wf.phases] == \
        [s.name for s in seen if not s.final() and not s.waiting]


def test_a_walk_stops_on_the_event_it_cannot_take():
    m = machine.Machine()
    seen, refused = m.walk(["ok", "redo"])
    assert refused == "redo"
    assert [str(s) for s in seen] == ["research", "planning"]


def test_an_end_takes_nothing_and_the_two_of_them_are_different():
    m = machine.Machine()
    done, attention = machine.State(machine.DONE), machine.State(machine.ATTENTION)
    assert done.final() and attention.final()
    assert done != attention
    for state in (done, attention):
        assert [e for e in machine.EVENTS if m.step(state, e) is not None] == []
    assert m.walk(HAPPY + ["ok"])[1] == "ok"


def test_every_state_that_is_not_an_end_has_somewhere_to_go():
    m = machine.Machine()
    for state in m.states():
        moves = [e for e in machine.EVENTS if m.step(state, e) is not None]
        if state.final():
            assert moves == [], str(state)
        else:
            assert moves, str(state)


def test_nothing_in_the_table_is_out_of_reach():
    """a state the file allows and no run can sit in would be the file
    describing a situation that cannot happen. there is not one."""
    m = machine.Machine()
    assert m.unreachable() == []
    assert len(m.reachable()) == len(m.states())


def test_the_refusals_are_the_table_turned_over():
    m = machine.Machine()
    working = [s for s in m.states() if not s.final()]
    assert len(m.table()) + len(m.refusals()) == len(working) * len(machine.EVENTS)
    assert len(m.table()) == 19


def test_a_phase_list_that_is_not_the_one_in_the_repo():
    """it is built from a Workflow, so the file is an argument and not a fact."""
    m = machine.Machine(a_workflow([{"name": "one", "gate": "user"},
                                    {"name": "two", "loop": 2}]))
    assert [str(s) for s in m.states()] == [
        "one", "one (waiting)", "two", "two #2", "done", "attention"]
    seen, refused = m.walk(["ok", "approve", "redo", "ok"])
    assert refused is None
    assert [str(s) for s in seen] == ["one", "one (waiting)", "two", "two #2", "done"]


def test_a_workflow_with_no_phases_starts_where_it_ends():
    m = machine.Machine(a_workflow([]))
    assert m.start().final()
    assert [str(s) for s in m.states()] == ["done", "attention"]
    assert m.table() == []


def test_a_gate_on_a_looping_phase_waits_on_each_trip():
    """no phase in the file is both, and the two keys are independent, so the
    machine says what it would be rather than leaving it to be found out."""
    m = machine.Machine(a_workflow([{"name": "one", "gate": "user", "loop": 2}]))
    assert [str(s) for s in m.states()] == [
        "one", "one (waiting)", "one #2", "one #2 (waiting)", "done", "attention"]
    assert m.step(machine.State("one", 2), machine.OK) == \
        machine.State("one", 2, waiting=True)


def test_the_report_prints_the_states_and_the_gaps():
    text = "\n".join(machine.report())
    assert "8 phases, 16 states, 19 moves" in text
    assert "planning (waiting)        approve -> feature doc" in text
    assert "redo -> attention" in text
    assert "no move written for a refusal  (7 of 8 phases)" in text
    assert "out of reach  (0)" in text
