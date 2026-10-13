"""the labelled lines of an answer, read one way: outside fences, not quoted,
whatever their case, bullet or bold."""
import sys

sys.path.insert(0, ".")
from agentweft.runner import handoff, verbs


def test_a_needs_line_is_read_and_the_first_one_wins():
    v = verbs.parse("TEST: t.py\nNEEDS: which is right?\nNEEDS: a second\n")
    assert v.needs == "which is right?"
    assert bool(v)


def test_a_needs_inside_a_code_fence_is_text_not_a_verb():
    text = ("TEST: t.py\n\n```python\ndef test_x():\n"
            "    assert out == 'NEEDS: x'\n```\n")
    assert verbs.parse(text).needs is None
    assert not verbs.parse(text)


def test_a_quoted_needs_from_the_task_is_not_honoured():
    assert verbs.parse("> NEEDS: the pasted report said this\n").needs is None


def test_lower_case_bulleted_and_bold_keys_are_honoured():
    assert verbs.parse("needs: which is right?\n").needs == "which is right?"
    assert verbs.parse("- NEEDS: which?\n").needs == "which?"
    assert verbs.parse("**REFUSED:** TASK.md:12 says no\n").refused \
        == "TASK.md:12 says no"


def test_list_verbs_gather_their_own_line_and_the_bullets_under_them():
    v = verbs.parse("NEEDS: keep or change?\nCITES:\n- TASK.md:158 - strings\n"
                    "- tests/test_export.py:13\nOPTIONS:\n- A: keep\n- B: change\n"
                    "\nprose ends the list\n- not an option\n")
    assert v.cites == ["TASK.md:158 - strings", "tests/test_export.py:13"]
    assert v.options == ["A: keep", "B: change"]


def test_assumed_and_changed_under_and_intent_are_read():
    v = verbs.parse("INTENT: override\nINTENT QUOTE: \"change X to Y\"\n"
                    "INTENT SCOPE: the json export\nASSUMED: ints | why: x"
                    " | if wrong: y\nCHANGED UNDER: 2026-10-12 12:30\n")
    assert (v.intent, v.intent_quote) == ("override", "change X to Y")
    assert v.intent_scope == ["the json export"]
    assert v.assumed == ["ints | why: x | if wrong: y"]
    assert v.changed_under == ["2026-10-12 12:30"]


def test_the_handoff_block_is_read_on_the_same_visible_lines():
    fenced = "```\nHANDOFF\nDID:\n- in a fence\nEND HANDOFF\n```\n"
    assert handoff.parse(fenced)["state"] == "missing"
    quoted = "> HANDOFF\n> DID:\n> - quoted\n> END HANDOFF\n"
    assert handoff.parse(quoted)["state"] == "missing"


def test_key_of_normalises_the_name_and_strips_the_decoration():
    assert verbs.key_of("- **Must-not-miss:** spec:1") == \
        ("MUST NOT MISS", "spec:1", True, False)
    assert verbs.key_of("DID:") == ("DID", "", False, True)
    assert verbs.key_of("calc.py: add returns a + b") is None
    assert verbs.key_of("just prose") is None
