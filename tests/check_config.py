# run this by hand: python tests/check_config.py
import sys

sys.path.insert(0, ".")
import runner

# every flow loads and names its steps
for flow in ["weekly-digest", "ops-check", "summarise-and-check", "release-notes"]:
    cfg = runner.config(flow)
    assert cfg.get("name"), flow
    assert cfg["steps"], flow
    for s in runner.steps(flow):
        assert s.endswith(".md"), (flow, s)

# only the digest fans out
assert runner.fanout_step("weekly-digest") == "worker"
assert runner.fanout_step("ops-check") is None

# the verdict line is read off the first line only
assert runner.verdict("VERDICT: redo\nbecause x") == "redo"
assert runner.verdict("VERDICT: ok") == "ok"
assert runner.verdict("no verdict here") == "ok"

print("ok")
