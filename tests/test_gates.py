import sys

import pytest

sys.path.insert(0, ".")
from guardrails import gates


def test_regex_present():
    g = gates.build({"gate": "regex", "pattern": r"^## needs me"})
    assert g.run("## needs me\n- a")
    assert not g.run("## what changed\n- a")


def test_regex_absent():
    g = gates.build({"gate": "regex", "pattern": "TODO", "present": False})
    assert g.run("clean output")
    bad = g.run("TODO: finish this")
    assert not bad
    assert "should not" in bad.detail


def test_length_cap():
    g = gates.build({"gate": "length", "max_lines": 2})
    assert g.run("a\nb")
    assert not g.run("a\nb\nc")


def test_length_floor():
    g = gates.build({"gate": "length", "min_lines": 2})
    assert not g.run("a")


def test_an_unknown_gate_is_an_error_not_a_skip():
    with pytest.raises(ValueError):
        gates.build({"gate": "nonsense"})
