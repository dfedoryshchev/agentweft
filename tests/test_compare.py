import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import compare, workflow


def a_workflow(phase):
    """a workflow with one phase in it, for asking what a vocabulary is."""
    return workflow.Workflow({"name": "x", "lead": "lead", "phases": [phase]})


def by_label(rows):
    return dict((r.label, r) for r in rows)


def test_the_flow_vocabulary_is_the_loaders_own_key_lists():
    words = compare.flow_vocabulary()
    assert "flow.max_calls" in words
    assert "step.role" in words
    assert "promises.invariants" in words
    # promises is a container, so its three keys stand in for it
    assert "flow.promises" not in words


def test_the_phase_vocabulary_is_whatever_the_file_happens_to_say():
    """the asymmetry itself: one side publishes its keys, the other is read."""
    words = compare.phase_vocabulary(a_workflow({"name": "p", "cadence": "weekly"}))
    assert "phase.cadence" in words
    assert "phase.gate" not in words


def test_every_key_on_both_sides_has_been_placed():
    assert compare.unmapped() == ([], [])


def test_a_key_nobody_has_compared_yet_shows_up_as_unmapped():
    flow_side, phase_side = compare.unmapped(
        a_workflow({"name": "p", "cadence": "weekly"}))
    assert flow_side == []
    assert phase_side == ["phase.cadence"]


def test_the_map_places_each_term_on_the_side_that_owns_it():
    flow_words = compare.flow_vocabulary()
    phase_words = compare.phase_vocabulary()
    for pair in compare.MAP:
        if pair.flow:
            assert pair.flow in flow_words, pair.flow
        if pair.phase:
            assert pair.phase in phase_words, pair.phase
        assert pair.flow or pair.phase


def test_the_sides_are_not_the_same_size():
    # phase.gate left the phase-only column when the flow side grew a word for
    # stopping on purpose. the counts are the argument, so they move with it.
    assert len(compare.pairs()) == 9
    assert len(compare.flow_only()) == 17
    assert len(compare.phase_only()) == 4


def test_two_words_mean_different_things_depending_on_the_file():
    found = dict((word, (left, right)) for word, left, right in compare.collisions())
    assert sorted(found) == ["gate", "name"]
    # a step's gates are a program that fails the run; a phase's gate is a
    # person it waits for. same word, and only one of them checks anything.
    assert found["gate"] == (["step.gates"], ["phase.gate"])
    assert found["name"] == (["flow.name"], ["workflow.name", "phase.name"])


def test_one_word_used_by_both_sides_for_one_idea_is_agreement_not_collision():
    agreed = [compare.Pair("flow.name", "workflow.name")]
    assert compare.collisions(agreed) == []
    split = agreed + [compare.Pair("", "phase.name")]
    assert compare.collisions(split)[0][0] == "name"


def test_a_plural_is_the_same_word():
    assert compare._stem("step.gates") == compare._stem("phase.gate")


def test_the_census_counts_what_is_in_the_repo():
    rows = by_label(compare.census())
    wf = workflow.load()
    assert rows["ordered units"].phase == str(len(wf.phases)) + " phases"
    assert rows["named jobs"].phase.endswith(str(len(wf.agents())) + " distinct")
    assert rows["conditions in prose"].flow == "19 invariants"


def test_the_census_says_how_much_of_it_is_prose():
    rows = by_label(compare.census())
    # most invariants are prose the checker shrugs at, and every entry and
    # exit line is
    assert rows["of those, something checks"].flow == "3 of 19"
    assert rows["of those, something checks"].phase == "none of 16"


def test_the_census_says_which_side_runs():
    rows = by_label(compare.census())
    assert rows["something executes it"].flow == "20 of 20 steps"
    assert rows["something executes it"].phase == "0 of 8 phases"
    assert rows["checks that are programs"].phase == "none"


def test_the_report_names_the_problem_without_solving_it():
    text = "\n".join(compare.report())
    assert "one idea, two names" in text
    assert "the same word for two things" in text
    assert "which side gives" in text
    assert "nothing here has decided it" in text
