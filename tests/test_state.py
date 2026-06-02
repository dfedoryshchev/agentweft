import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.runner import state


def test_two_flows_do_not_clobber_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")

    # the old code read the whole dict, edited one key and wrote it all back,
    # so this second save used to wipe the first
    state.save_state("ops-check", {"last_run": "a.md"})
    state.save_state("weekly-digest", {"last_run": "b.md"})

    assert state.load_state("ops-check")["last_run"] == "a.md"
    assert state.load_state("weekly-digest")["last_run"] == "b.md"


def test_unknown_flow_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "nothing.json")
    assert state.load_state("never-run") == {}
