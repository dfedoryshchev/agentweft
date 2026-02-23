import sys

sys.path.insert(0, ".")
from guardrails.budget import Budget


def test_a_call_is_charged():
    b = Budget(max_calls=2)
    b.charge("hello", "world")
    assert b.calls == 1
    assert b.over() is None


def test_the_call_cap_trips():
    b = Budget(max_calls=1)
    b.charge("a", "b")
    b.charge("a", "b")
    assert "call cap" in b.over()


def test_the_token_cap_trips():
    b = Budget(max_tokens=1)
    b.charge("x" * 100, "y" * 100)
    assert "token cap" in b.over()


def test_a_cached_call_is_not_charged():
    # this is the one that bit me: a redo re-runs the flow, most of it comes
    # back from the cache, and the cap tripped on work that never happened
    b = Budget(max_calls=2)
    b.charge("a", "b")
    assert b.calls == 1
    assert b.over() is None
