import sys

import pytest

sys.path.insert(0, ".")
from flow import spec


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


def test_every_shipped_flow_passes_its_own_check():
    import runner
    for flow in ["weekly-digest", "ops-check", "summarise-and-check",
                 "release-notes", "code-review", "fix-with-test"]:
        runner.config(flow)
