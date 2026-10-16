import datetime
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.evals import __main__ as evals_main
from agentweft.evals import harness, recording
from agentweft.providers import Provider, Reply, fake_provider
from agentweft.providers.base import Usage
from agentweft.runner import engine, prompts

REPO = Path(__file__).resolve().parent.parent
FLOW = "weekly-digest"
DIGEST = ("VERDICT: ok\n\n## what changed\n- a.md | changed | x\n\n"
          "## needs me\n- b.md | needs-me | y\n")
PLAN = ("TASK: a.md\nLIST: changed\nWHY: x\nFILES:\n- a.md\n\n"
        "TASK: b.md\nLIST: needs-me\nWHY: y\nFILES:\n- b.md\n")


def nothing_is_called(monkeypatch):
    def ask(self, prompt, timeout=None):
        raise AssertionError("a replayed case called its provider")
    monkeypatch.setattr(fake_provider.FakeProvider, "ask", ask)


@pytest.fixture
def evals_root(tmp_path, monkeypatch):
    """a copy of the digest flow and an evals folder with one case of it, so a
    test can edit a prompt file and write a recording without touching the
    repo's own."""
    flows = tmp_path / "flows"
    shutil.copytree(REPO / "flows" / FLOW, flows / FLOW)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    root = tmp_path / "evals"
    case = root / FLOW / "cases" / "two-files"
    shutil.copytree(REPO / "evals" / FLOW / "cases" / "busy-week" / "inbox",
                    case / "inbox")
    (case / "case.yaml").write_text(yaml.safe_dump(
        {"inbox": "inbox", "provider": {"provider": "fake", "reply": DIGEST,
                                        "replies": {"planner.md": PLAN}},
         "expect": {"invariants": "all"}}), encoding="utf-8")
    monkeypatch.setattr(harness, "ROOT", root)
    monkeypatch.setattr(harness, "LAST", root / ".last.json")
    return case


def recorded(case):
    out = harness.run_flow_for(FLOW, harness.load_case(case), record=True)
    assert out[2] == ""
    return out


def entries(case):
    return json.loads((case / recording.FILE).read_text(encoding="utf-8"))


def rewrite(case, blob):
    (case / recording.FILE).write_text(json.dumps(blob), encoding="utf-8")


def test_a_recorded_case_replays_without_calling_anything(evals_root,
                                                          monkeypatch):
    live_out, live_budget, _ = recorded(evals_root)
    case = harness.load_case(evals_root)
    assert case["recording"] == evals_root / recording.FILE
    nothing_is_called(monkeypatch)
    out, budget, stopped = harness.run_flow_for(FLOW, case)
    assert stopped == ""
    assert out == live_out
    assert budget.calls == live_budget.calls == 5


def test_a_case_with_no_recording_runs_its_provider(evals_root):
    case = harness.load_case(evals_root)
    assert case["recording"] is None
    out, budget, stopped = harness.run_flow_for(FLOW, case)
    assert stopped == "" and budget.calls == 5


def test_a_recording_is_keyed_by_step_task_and_go_and_holds_the_prompt_hash(
        evals_root):
    before = datetime.datetime.now().replace(microsecond=0)
    recorded(evals_root)
    blob = entries(evals_root)
    stamp = datetime.datetime.fromisoformat(blob["recorded"])
    assert before <= stamp <= datetime.datetime.now()
    assert blob["provider"] == "fake"
    keys = [(c["step"], c["task"], c["go"]) for c in blob["calls"]]
    assert keys == [("merge.md", None, 1), ("planner.md", None, 1),
                    ("reviewer.md", None, 1), ("worker.md", 1, 1),
                    ("worker.md", 2, 1)]
    for c in blob["calls"]:
        assert len(c["prompt"]) == 64
        assert c["say"] == (PLAN if c["step"] == "planner.md" else DIGEST)
    assert "modified in the last 7 days" not in json.dumps(blob)


def test_an_edited_prompt_makes_the_replay_stale_not_a_pass(evals_root,
                                                            monkeypatch,
                                                            tmp_path):
    recorded(evals_root)
    planner = tmp_path / "flows" / FLOW / "planner.md"
    planner.write_text(planner.read_text(encoding="utf-8")
                       + "\nkeep it short.\n", encoding="utf-8")
    nothing_is_called(monkeypatch)
    out, budget, stopped = harness.run_flow_for(FLOW,
                                                harness.load_case(evals_root))
    assert stopped == "recording is stale: planner.md prompt changed"
    assert out == ""


def test_a_call_the_recording_does_not_have_is_an_error(evals_root,
                                                        monkeypatch):
    recorded(evals_root)
    blob = entries(evals_root)
    blob["calls"] = [c for c in blob["calls"] if c["step"] != "reviewer.md"]
    rewrite(evals_root, blob)
    nothing_is_called(monkeypatch)
    _, _, stopped = harness.run_flow_for(FLOW, harness.load_case(evals_root))
    assert stopped == "recording has no answer for reviewer.md go 1"


def test_an_answer_the_run_never_asked_for_is_an_error(evals_root, monkeypatch):
    recorded(evals_root)
    blob = entries(evals_root)
    extra = dict(blob["calls"][-1], go=2)
    blob["calls"].append(extra)
    rewrite(evals_root, blob)
    nothing_is_called(monkeypatch)
    _, _, stopped = harness.run_flow_for(FLOW, harness.load_case(evals_root))
    assert stopped == ("recording has answers the run never asked for: "
                       "worker.md task 2 go 2")


def test_line_endings_do_not_change_a_prompt_hash():
    assert recording.digest("a\r\nb\r\n") == recording.digest("a\nb\n")
    assert recording.digest("a\nb\n") != recording.digest("a\nc\n")


class Flaky(Provider):
    """times out once on the first step, then answers like the fake."""

    name = "flaky"

    def __init__(self, **opts):
        Provider.__init__(self, **opts)
        self.goes = 0
        self.step = None

    def at(self, step, task):
        self.step = step

    def ask(self, prompt, timeout=None):
        self.goes += 1
        if self.goes == 1:
            return Reply("", detail="timed out", retryable=True)
        said = PLAN if self.step == "planner.md" else DIGEST
        return Reply(said, model="flaky-1", cost=0.02,
                     usage=Usage({"input_tokens": 10, "output_tokens": 3}))


def test_a_failed_go_is_recorded_and_replayed_as_one(evals_root, monkeypatch):
    real = engine.retry
    monkeypatch.setattr(engine, "retry",
                        lambda f, cap=3: real(f, cap, sleep=lambda s: None))
    live = recording.Recorder(Flaky())
    live_out, live_budget, _ = engine.run_once(FLOW, provider=live)
    blob = live.blob()
    first = [c for c in blob["calls"] if c["step"] == "planner.md"]
    assert [(c["go"], c["say"], c["detail"]) for c in first] == [
        (1, "", "timed out"), (2, PLAN, "")]
    again = recording.Replay(json.loads(json.dumps(blob)))
    out, budget, _ = engine.run_once(FLOW, provider=again)
    assert again.unused() == []
    assert out == live_out
    assert budget.calls == live_budget.calls == 6
    assert budget.spent() == live_budget.spent()


def test_the_command_replays_and_a_stale_one_fails_and_keeps_the_baseline(
        evals_root, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["evals", FLOW, "--record"])
    assert evals_main.main() == 0
    assert (evals_root / recording.FILE).exists()
    baseline = harness.LAST.read_text(encoding="utf-8")
    capsys.readouterr()

    nothing_is_called(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["evals", FLOW])
    assert evals_main.main() == 0
    line = [l for l in capsys.readouterr().out.split("\n")
            if l.strip().startswith("two-files")][0]
    assert line.endswith(", replayed")

    reviewer = tmp_path / "flows" / FLOW / "reviewer.md"
    reviewer.write_text(reviewer.read_text(encoding="utf-8") + "\nbe brief.\n",
                        encoding="utf-8")
    assert evals_main.main() == 1
    printed = capsys.readouterr().out
    assert "recording is stale: reviewer.md prompt changed" in printed
    assert "not saved" in printed
    assert harness.LAST.read_text(encoding="utf-8") == baseline


def test_one_case_can_be_recorded_on_its_own(evals_root, monkeypatch, capsys):
    other = evals_root.parent / "another"
    shutil.copytree(evals_root, other)
    monkeypatch.setattr(sys, "argv", ["evals", FLOW])
    assert evals_main.main() == 0
    monkeypatch.setattr(sys, "argv", ["evals", FLOW, "--case", "another",
                                      "--record"])
    assert evals_main.main() == 0
    assert (other / recording.FILE).exists()
    assert not (evals_root / recording.FILE).exists()
    kept = json.loads(harness.LAST.read_text(encoding="utf-8"))[FLOW]
    assert sorted(kept) == ["another", "two-files"]
    monkeypatch.setattr(sys, "argv", ["evals", FLOW, "--case", "nope"])
    assert evals_main.main() == 1
    assert "no case called nope" in capsys.readouterr().out


def test_the_shipped_recorded_case_replays_what_it_does_live(monkeypatch):
    path = [p for p in harness.cases_for(FLOW) if p.name == "quiet-week"][0]
    case = harness.load_case(path)
    assert case["recording"] is not None
    live = dict(case, recording=None)
    spec = engine.config(FLOW)
    was = harness.run_flow_for(FLOW, live)
    want = harness.score(spec, *was, steps=was.steps, expect=case["expect"])
    nothing_is_called(monkeypatch)
    now = harness.run_flow_for(FLOW, case)
    got = harness.score(spec, *now, steps=now.steps, expect=case["expect"])
    assert got["rows"] == want["rows"]
    assert (got["calls"], got["tokens"]) == (want["calls"], want["tokens"])
