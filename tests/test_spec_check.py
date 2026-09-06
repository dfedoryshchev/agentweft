import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec


def test_a_good_spec_loads():
    s = spec.load({"name": "x", "steps": [{"role": "worker"}]})
    assert s.name == "x"


def test_missing_steps_is_caught():
    with pytest.raises(ValueError) as e:
        spec.load({"name": "x"})
    assert "missing steps" in str(e.value)


def test_a_typo_is_caught():
    # this used to load fine and then quietly time out at the default
    with pytest.raises(ValueError) as e:
        spec.load({"name": "x", "steps": [{"role": "worker"}], "timeouts": 10})
    assert "unknown key timeouts" in str(e.value)


def test_a_step_without_a_role_is_caught():
    with pytest.raises(ValueError) as e:
        spec.load({"name": "x", "steps": [{"prompt": "worker.md"}]})
    assert "step 0 has no role" in str(e.value)


def test_a_step_may_declare_what_it_is_allowed_to_touch():
    s = spec.load({"name": "x",
                   "steps": [{"role": "architect", "tools": ["read", "grep"]}]})
    assert s.steps[0]["tools"] == ["read", "grep"]


def test_a_grant_nothing_has_a_name_for_is_refused():
    """the vocabulary is the words the agent files actually use.

    a typo in a grant is the failure this layer exists to catch. `shel` is not
    a narrower grant than `shell`, it is no grant at all, and a boundary check
    holding a word nothing means looks exactly like one that found nothing.
    """
    bad = spec.check({"name": "x", "steps": [{"role": "w", "tools": ["shel"]}]})
    assert bad == ["step 0: no such tool shel. there is: read, grep, write, "
                   "edit, shell, browser"]


def test_a_grant_is_a_list_and_one_word_is_not_one():
    """`tools: shell` reads fine and iterates as five letters.

    left alone it would grant s, h, e, l and l, none of which is a tool, so
    the refusal has to be about the shape before it is about the words.
    """
    bad = spec.check({"name": "x", "steps": [{"role": "w", "tools": "shell"}]})
    assert bad == ["step 0: tools should be a list"]


def test_granting_nothing_is_a_thing_a_step_can_say():
    """an empty list is a boundary, not a missing one - it allows nothing."""
    assert spec.check({"name": "x", "steps": [{"role": "w", "tools": []}]}) == []


def test_every_shipped_flow_passes_its_own_check():
    from agentweft import runner
    for flow in ["weekly-digest", "ops-check", "summarise-and-check",
                 "release-notes", "code-review", "fix-with-test"]:
        runner.config(flow)
