import sys

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.guardrails import boundary


def test_a_step_that_declared_no_grant_has_no_boundary_to_cross():
    """None is "said nothing"; [] is "said nothing is allowed".

    every flow in the repo is the first case, so getting these the wrong way
    round would flag every step of every run the first time one printed a
    command, which is the shape of a check nobody leaves switched on.
    """
    assert boundary.check("$ rm -rf /\n", None) == []
    assert boundary.check("$ rm -rf /\n", []) != []


def test_every_mark_asks_for_a_tool_the_checker_knows():
    """the marks and the flow checker have to mean the same six words.

    a mark needing a grant no step could ever be given can never be satisfied,
    and it would read as a finding about the step rather than about this file.
    """
    for mark in boundary.MARKS:
        assert mark.needs
        # every mark is a heuristic, so it has to carry the argument against
        # itself into the note. `RESIDUE` is held to the same thing.
        assert mark.why.strip()
        for tool in mark.needs:
            assert tool in spec.GRANTS, tool
    for tool in boundary.UNSEEN:
        assert tool in spec.GRANTS, tool


def test_what_it_cannot_see_is_named_rather_than_passed_over():
    """a grant this cannot check has to say so, the way an unmatched invariant
    does. silence would read as "checked, nothing found"."""
    assert set(boundary.MARKED) | set(boundary.UNSEEN) == set(spec.GRANTS)
    assert all(why.strip() for why in boundary.UNSEEN.values())
