import sys

sys.path.insert(0, ".")
from agentweft.guardrails import promises

DIGEST = '''## what changed
- notes.md | changed | moved
- plan.md | changed | rewritten

## needs me
- budget.md | needs-me | sign by friday

## can wait
- old.md | can-wait | nothing
'''


def test_a_clean_digest_breaks_nothing():
    invs = ["no file appears in two lists", "every line names a file"]
    assert promises.failures(DIGEST, invs) == []


def test_a_file_in_two_lists_is_caught():
    bad = DIGEST + "\n## can wait\n- notes.md | can-wait | also here\n"
    out = promises.failures(bad, ["no file appears in two lists"])
    assert out and "notes.md" in out[0][1]


def test_a_line_with_no_filename_is_caught():
    bad = DIGEST + "- something vague\n"
    assert promises.failures(bad, ["every line names a file"])


def test_an_uncheckable_invariant_says_so_rather_than_passing():
    got = promises.check(DIGEST, ["the tone is appropriate"])
    assert got[0][1] is None
    assert "not checkable" in got[0][2]
