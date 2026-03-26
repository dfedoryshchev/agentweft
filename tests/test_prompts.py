import os
import sys

sys.path.insert(0, ".")
import runner
from roles import resolver


def test_env_keys_are_substituted(monkeypatch):
    monkeypatch.setenv("INBOX", "C:/somewhere")
    assert runner.load_prompt.__module__
    from runner import prompts
    assert prompts.substitute("read {INBOX} now") == "read C:/somewhere now"


def test_an_unknown_brace_is_left_alone():
    from runner import prompts
    assert prompts.substitute("keep {THIS}") == "keep {THIS}"


def test_every_role_gets_the_shared_fragments():
    cfg = runner.config("weekly-digest")
    by_role = resolver.resolve(cfg.raw, runner.flow_path("weekly-digest"))
    for role, rules in by_role.items():
        assert "markdown only" in rules
        assert "never invent a number" in rules


def test_only_the_judging_roles_get_the_extra_block():
    cfg = runner.config("weekly-digest")
    by_role = resolver.resolve(cfg.raw, runner.flow_path("weekly-digest"))
    assert "allowed to say the work is wrong" in by_role["reviewer"]
    assert "allowed to say the work is wrong" not in by_role["planner"]
