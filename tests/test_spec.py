import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import spec


def test_a_flow_without_promises_still_loads():
    s = spec.load({"name": "x", "steps": [{"role": "worker"}]})
    assert s.name == "x"
    assert s.promises.invariants == []
    assert s.promises.as_prompt() == ""


def test_invariants_become_prompt_text():
    s = spec.load({"name": "x", "steps": [],
                   "promises": {"invariants": ["no file twice", "every line names a file"]}})
    text = s.promises.as_prompt()
    assert "no file twice" in text
    assert "every line names a file" in text


def test_the_digest_promises_what_it_says_it_does():
    s = runner.config("weekly-digest")
    assert "no file appears in two lists" in s.promises.invariants
    assert s.promises.inputs


def test_raw_keys_still_reachable():
    s = runner.config("ops-check")
    assert s.get("timeout")
    assert s["steps"]
