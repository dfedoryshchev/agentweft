import sys

sys.path.insert(0, ".")
import runner


def test_every_flow_loads():
    for flow in ["weekly-digest", "ops-check", "summarise-and-check", "release-notes"]:
        cfg = runner.config(flow)
        assert cfg.get("name")
        assert cfg["steps"]


def test_step_files_are_md():
    for flow in ["weekly-digest", "ops-check"]:
        for s in runner.steps(flow):
            assert s.endswith(".md")


def test_only_the_digest_fans_out():
    assert runner.fanout_step("weekly-digest") == "worker"
    assert runner.fanout_step("ops-check") is None


def test_verdict_reads_the_first_line_only():
    assert runner.verdict("VERDICT: redo\nbecause x") == "redo"
    assert runner.verdict("VERDICT: ok") == "ok"
    assert runner.verdict("no verdict here") == "ok"
