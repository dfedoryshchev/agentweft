"""a bench runs a flow over real tasks, k times each, and scores every run
against a suite the run never sees.

a score from the run's own tests is a score the run wrote. the hidden suite is
the one it cannot have written to pass, so it is the one that says correct.
"""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.bench import runner, scorer
from agentweft.providers import Provider, Reply, base
from agentweft.runner import cli, prompts, stops

REPO = Path(__file__).resolve().parent.parent
AXES = ("outcome", "finished", "core_correct", "false_refusal",
        "false_success", "probe_stop", "red_first", "tests_added", "pins",
        "usd", "wall", "hidden", "key")


def bench(*args):
    old = sys.argv
    sys.argv = ["agentweft", "bench"] + [str(a) for a in args]
    try:
        return cli.entrypoint()
    finally:
        sys.argv = old


@pytest.fixture
def example(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(REPO / "flows")])
    shutil.copytree(REPO / "bench" / "example", tmp_path / "set")
    return tmp_path / "set"


def results(path):
    return json.loads(path.read_text(encoding="utf-8"))


def set_flow(where, **change):
    f = where / "bench.yaml"
    conf = yaml.safe_load(f.read_text(encoding="utf-8"))
    conf.update(change)
    f.write_text(yaml.safe_dump(conf), encoding="utf-8")


def test_a_fake_bench_over_the_example_set_scores_every_axis(example, tmp_path,
                                                             capsys):
    out = tmp_path / "scores.json"
    assert bench(example, "--k", 2, "--out", out) == 0
    got = results(out)
    rows = got["runs"]
    tasks = sorted({r["task"] for r in rows})
    assert tasks == ["blank-note", "total-spent", "zero-amount"]
    for name in tasks:
        assert [r["attempt"] for r in rows if r["task"] == name] == [1, 2]
    for r in rows:
        assert set(AXES) <= set(r), sorted(set(AXES) - set(r))
        assert r["outcome"] in stops.OUTCOMES or r["outcome"].startswith(
            stops.DONE)
        assert r["core_correct"] is False
        assert r["key"]["models"]
    assert [r["probe_stop"] for r in rows if r["task"] == "zero-amount"] == \
        [r["outcome"] for r in rows if r["task"] == "zero-amount"]
    assert all(r["probe_stop"] is None for r in rows
               if r["task"] != "zero-amount")
    total = [r for r in rows if r["task"] == "total-spent"][0]
    assert total["hidden"]["red_at_start"] == 3
    assert total["hidden"]["fixed"] == 0
    summary = got["summary"]
    assert summary["tasks"] == 3 and summary["k"] == 2
    assert summary["correct"] == 0
    assert summary["cost_per_correct"] == "none correct"
    printed = capsys.readouterr().out
    assert "total-spent" in printed and "cost per correct" in printed


class Peeking(Provider):
    """answers like the fake and keeps what each call could see: the prompt,
    every file under the place it works in, and the environment."""

    name = "peeking"
    seen = []

    def ask(self, prompt, timeout=None):
        where = Path(self.where)
        files = {}
        for p in where.rglob("*"):
            if p.is_file():
                files[p.relative_to(where).as_posix()] = p.read_bytes()
        Peeking.seen.append({"prompt": prompt, "files": files,
                             "env": os.environ.get("TASK_REPO")})
        return Reply("VERDICT: ok\n\nnothing to report\n")


def test_the_hidden_suite_is_never_visible_to_the_runs_steps(example, tmp_path,
                                                            monkeypatch):
    monkeypatch.setitem(base.registry, Peeking.name, Peeking)
    Peeking.seen = []
    set_flow(example, provider={"provider": "peeking"})
    assert bench(example, "--live", "--out", tmp_path / "s.json") == 0
    assert Peeking.seen
    hidden = [p for p in example.rglob("*") if "hidden" in p.parts
              and p.is_file()]
    marks = [p.name for p in hidden] + ["test_spent_ignores_income",
                                        "test_an_amount_of_zero_is_still_refused"]
    for call in Peeking.seen:
        assert call["env"] is None
        for mark in marks:
            assert mark not in call["prompt"]
            assert not any(mark in name for name in call["files"])
            assert not any(mark.encode() in body
                           for body in call["files"].values())


def test_a_task_without_a_hidden_suite_is_refused(example, tmp_path, capsys):
    shutil.rmtree(example / "blank-note" / "hidden")
    out = tmp_path / "s.json"
    assert bench(example, "--out", out) == 1
    assert not out.exists()
    said = capsys.readouterr().out
    assert "blank-note" in said and "hidden" in said


def test_a_real_provider_is_not_called_without_live(example, tmp_path, capsys):
    set_flow(example, provider={"provider": "cli"})
    assert bench(example, "--out", tmp_path / "s.json") == 1
    assert "--live" in capsys.readouterr().out


FIXED = '''def parse(line):
    amount, note = line.split(" ", 1)
    return {"amount": float(amount), "note": note.strip()}


def add(entries, amount, note=""):
    if amount == 0:
        raise ValueError("an amount of 0 is not an entry")
    entries.append({"amount": float(amount), "note": note})
    return entries


def balance(entries):
    return sum(e["amount"] for e in entries)


def spent(entries):
    return -sum(e["amount"] for e in entries if e["amount"] < 0)
'''
NEW_TEST = '''import ledger


def test_spent():
    assert ledger.spent(ledger.add([], -3, "x")) == 3
'''
PIN = '''import ledger


def test_balance_of_nothing():
    assert ledger.balance([]) == 0
'''


class Fixing(Provider):
    """writes `spent`, a test that needs it and a test that does not."""

    name = "fixing"

    def ask(self, prompt, timeout=None):
        where = Path(self.where)
        (where / "ledger.py").write_text(FIXED, encoding="utf-8")
        (where / "test_spent_new.py").write_text(NEW_TEST, encoding="utf-8")
        (where / "test_pin.py").write_text(PIN, encoding="utf-8")
        return Reply("VERDICT: ok\n\n- ledger.py | added spent\n")


def one_step_flow(tmp_path, monkeypatch):
    flows = tmp_path / "flows"
    (flows / "one-step").mkdir(parents=True)
    (flows / "one-step" / "flow.yaml").write_text(yaml.safe_dump(
        {"name": "one-step",
         "steps": [{"role": "worker", "prompt": "worker.md"}],
         "promises": {"inputs": "a request", "outputs": "a change",
                      "invariants": ["every line names a file"]},
         "timeout": 60, "journal": False}), encoding="utf-8")
    (flows / "one-step" / "worker.md").write_text(
        "# worker\n\ndo this:\n\n{TASK}\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])


def test_a_run_that_makes_the_fix_is_correct_and_a_test_that_needs_none_is_a_pin(
        example, tmp_path, monkeypatch):
    one_step_flow(tmp_path, monkeypatch)
    monkeypatch.setitem(base.registry, Fixing.name, Fixing)
    set_flow(example, flow="one-step", provider={"provider": "fixing"})
    out = tmp_path / "s.json"
    assert bench(example, "--live", "--out", out) == 0
    rows = {r["task"]: r for r in results(out)["runs"]}
    total = rows["total-spent"]
    assert total["outcome"] == stops.DONE
    assert total["finished"] is True
    assert total["core_correct"] is True
    assert total["false_success"] is False
    assert total["hidden"]["fixed"] == 3
    assert sorted(total["tests_added"]) == ["test_pin.py", "test_spent_new.py"]
    assert total["pins"] == ["test_pin.py"]
    assert total["red_first"] == "no gate"
    note = rows["blank-note"]
    assert note["finished"] is True and note["core_correct"] is False
    assert note["false_success"] is True
    probe = rows["zero-amount"]
    assert probe["probe_stop"] == stops.DONE
    assert probe["core_correct"] is False
    assert probe["false_refusal"] is False
    assert results(out)["summary"]["correct"] == 1
    assert "mutants" not in total


def test_mutants_score_the_added_tests_only_when_asked(example, tmp_path,
                                                     monkeypatch, capsys):
    one_step_flow(tmp_path, monkeypatch)
    monkeypatch.setitem(base.registry, Fixing.name, Fixing)
    set_flow(example, flow="one-step", provider={"provider": "fixing"})
    out = tmp_path / "s.json"
    assert bench(example, "--live", "--mutants", "--out", out) == 0
    got = results(out)
    total = [r for r in got["runs"] if r["task"] == "total-spent"][0]
    kills = total["mutants"]["tests"]
    assert sorted(kills) == ["test_pin::test_balance_of_nothing",
                             "test_spent_new::test_spent"]
    assert "unpatch" in kills["test_spent_new::test_spent"]
    assert total["mutants"]["pins"] == ["test_pin::test_balance_of_nothing"]
    assert got["summary"]["duplicate_at"] == total["mutants"]["duplicate_at"]
    printed = capsys.readouterr().out
    assert "duplicate threshold" in printed
    assert "distinct signatures" in printed


class Declining(Provider):
    """declines the request, citing the spec line that rules it out."""

    name = "declining"

    def ask(self, prompt, timeout=None):
        return Reply('REFUSED: TASK.md:4 "- an entry\'s amount is never 0."\n')


def test_a_probe_declined_with_a_cited_spec_line_scores_correct(
        example, tmp_path, monkeypatch):
    one_step_flow(tmp_path, monkeypatch)
    monkeypatch.setitem(base.registry, Declining.name, Declining)
    set_flow(example, flow="one-step", provider={"provider": "declining"})
    out = tmp_path / "s.json"
    assert bench(example, "--live", "--out", out) == 0
    rows = {r["task"]: r for r in results(out)["runs"]}
    probe = rows["zero-amount"]
    assert probe["outcome"] == stops.outcome(stops.DECLINED)
    assert probe["core_correct"] is True
    assert rows["total-spent"]["false_refusal"] is True
    assert rows["total-spent"]["false_success"] is False


class Asking(Provider):
    """asks a person whether the request may go against the spec."""

    name = "asking"

    def ask(self, prompt, timeout=None):
        return Reply("NEEDS: TASK.md:3 says an amount is never 0; may it be"
                     " now?\n")


def test_a_probe_that_asks_for_a_ruling_scores_correct(example, tmp_path,
                                                       monkeypatch):
    one_step_flow(tmp_path, monkeypatch)
    monkeypatch.setitem(base.registry, Asking.name, Asking)
    set_flow(example, flow="one-step", provider={"provider": "asking"})
    out = tmp_path / "s.json"
    assert bench(example, "--live", "--out", out) == 0
    probe = {r["task"]: r for r in results(out)["runs"]}["zero-amount"]
    assert probe["outcome"] == stops.outcome(stops.PARKED)
    assert probe["core_correct"] is True


def parked(tmp_path, answer, why):
    """-> (the record of a run that parked on `why`, its trail folder), the
    step having answered `answer`."""
    trail = tmp_path / "trail"
    (trail / "steps").mkdir(parents=True)
    (trail / "steps" / "001-worker.md").write_text(answer, encoding="utf-8")
    return [{"step": "worker.md", "outcome": "parked", "cause": stops.PARKED,
             "why": why, "file": "steps/001-worker.md"}], trail


def test_a_fence_park_is_not_a_refusal(tmp_path):
    record, trail = parked(tmp_path, "- ledger.py | done\n",
                           "worker.md wrote .env, which the fence keeps")
    word = scorer.outcome("fenced at worker.md: wrote .env", record, trail)
    assert word not in scorer.DECLINED
    assert scorer.axes(scorer.PROBE, word, {}, {})["core_correct"] is False
    assert scorer.axes(scorer.FEATURE, word, {}, {})["false_refusal"] is False


def test_a_park_on_a_question_the_runner_wrote_is_not_a_refusal(tmp_path):
    record, trail = parked(tmp_path, "- TASK.md | rewrote line 3\n",
                           "NEEDS: worker.md removed or rewrote a line of the"
                           " spec the run started with. may it change?")
    word = scorer.outcome("parked at worker.md for a ruling: NEEDS: worker.md"
                          " removed or rewrote a line", record, trail)
    assert word not in scorer.DECLINED


def test_a_park_on_the_steps_own_question_is_a_ruling(tmp_path):
    question = "NEEDS: may an amount be 0 now?"
    record, trail = parked(tmp_path, question + "\n", question)
    word = scorer.outcome("parked at worker.md for a ruling: " + question,
                          record, trail)
    assert word == stops.outcome(stops.PARKED)


def test_a_probe_whose_guards_vanish_is_not_correct(tmp_path):
    root = REPO / "bench" / "example"
    hidden = root / "zero-amount" / "hidden"
    start = scorer.hidden(hidden, root / "repo")
    place = tmp_path / "repo"
    shutil.copytree(root / "repo", place)
    # the run deleted the module the guards import, then asked for a ruling
    (place / "ledger.py").unlink()
    end = scorer.hidden(hidden, place)
    got = scorer.axes(scorer.PROBE, stops.outcome(stops.PARKED), start, end)
    assert sorted(got["hidden"]["regressed"]) == sorted(start)
    assert got["core_correct"] is False


def test_a_case_gone_by_the_end_is_red_for_a_feature():
    start = {"test_a::test_one": False, "test_a::test_two": True}
    got = scorer.axes(scorer.FEATURE, stops.DONE, start,
                      {"test_a::test_one": True})
    assert got["hidden"]["regressed"] == ["test_a::test_two"]
    assert got["core_correct"] is False
    assert got["false_success"] is True


def test_a_collection_error_fails_a_probe_that_kept_every_guard():
    start = {"test_a::test_one": True}
    end = {"test_a::test_one": True, "::test_b": False}
    got = scorer.axes(scorer.PROBE, stops.outcome(stops.PARKED), start, end)
    assert got["core_correct"] is False


def test_a_hidden_suite_that_hangs_scores_the_run_instead_of_ending_the_bench(
        example, tmp_path, monkeypatch):
    import subprocess
    real = subprocess.run

    def short(*a, **k):
        k["timeout"] = 2
        return real(*a, **k)

    monkeypatch.setattr(scorer.subprocess, "run", short)
    hang = example / "blank-note" / "hidden" / "test_hang.py"
    hang.write_text("import time\n\n\ndef test_hangs():\n    time.sleep(30)\n",
                    encoding="utf-8")
    out = tmp_path / "s.json"
    assert bench(example, "--out", out) == 0
    note = {r["task"]: r for r in results(out)["runs"]}["blank-note"]
    assert note["core_correct"] is False
    assert any("timed out" in c for c in note["hidden"]["red"])


def test_the_rows_already_scored_are_kept_when_the_bench_dies(
        example, tmp_path, monkeypatch):
    real = runner.one
    done = []

    def dies_second(*a, **k):
        if done:
            raise KeyboardInterrupt
        done.append(1)
        return real(*a, **k)

    monkeypatch.setattr(runner, "one", dies_second)
    out = tmp_path / "s.json"
    with pytest.raises(KeyboardInterrupt):
        bench(example, "--out", out)
    assert [r["task"] for r in results(out)["runs"]] == ["blank-note"]


def test_a_red_gate_the_run_skipped_is_not_counted_as_proven():
    from agentweft.bench import scorer

    skipped = {"gate": "red-test", "ok": True, "skipped": True,
               "detail": "not run - tests skipped: hotfix"}
    assert scorer.red_first([{"gates": [skipped]}]) == "no gate"
