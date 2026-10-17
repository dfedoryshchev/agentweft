"""more than one reviewer on a change, each reading for something the others
do not, and `reviewers:` saying how many of them a flow runs."""
import sys

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.runner import engine

from test_trace import CLAUDE, a_flow, answer, every_line

SPEC_LENS = "the spec, each thing it asks for has code and a test"
RUN_LENS = "what the tests do not run, the edges run by hand"


def two(reviewers=None, lenses=(SPEC_LENS, RUN_LENS)):
    raw = {"name": "x", "steps": [
        {"role": "worker"},
        {"role": "reviewer", "prompt": "reads.md", "on_redo": "worker"},
        {"role": "reviewer", "prompt": "runs.md", "on_redo": "worker"}]}
    for step, lens in zip(raw["steps"][1:], lenses):
        if lens is not None:
            step["lens"] = lens
    if reviewers is not None:
        raw["reviewers"] = reviewers
    return raw


# what the flow file may say


def test_two_reviewers_with_a_lens_each_load():
    assert spec.check(two(2)) == []
    assert [s.get("lens") for s in spec.load(two(2)).steps[1:]] == \
        [SPEC_LENS, RUN_LENS]


def test_reviewers_keeps_that_many_of_them_in_flow_order():
    loaded = spec.load(two(1))
    assert [spec.step_id(s) for s in loaded.steps] == ["worker.md", "reads.md"]


@pytest.mark.parametrize("said", [0, 3, -1, "two", True, 1.5])
def test_reviewers_is_a_count_of_the_reviewer_steps_the_flow_has(said):
    assert spec.check(two(said)) == [
        "reviewers should be a whole number from 1 to 2, the reviewer steps"
        " this flow has"]


def test_a_reviewer_with_no_lens_beside_one_with_a_lens_is_refused():
    assert spec.check(two(lenses=(SPEC_LENS, None))) == [
        "step 2: a flow with more than one reviewer gives each a lens: the"
        " one line of what it reads for that the others do not"]


def test_reviewers_asks_for_a_lens_on_each_reviewer():
    assert len(spec.check(two(2, lenses=(None, None)))) == 2


def test_two_reviewers_reading_for_the_same_thing_are_refused():
    assert spec.check(two(2, lenses=(SPEC_LENS, " " + SPEC_LENS))) == [
        "step 2: lens is the same as step 1's; a second reviewer reads for"
        " what the first does not"]


def test_a_lens_is_a_line_of_words_on_a_reviewer():
    assert spec.check(two(lenses=(SPEC_LENS, ""))) == [
        "step 2: lens should be one line saying what this reviewer reads for"]
    raw = two()
    raw["steps"][0]["lens"] = "the code"
    assert spec.check(raw) == ["step 0: lens is for a reviewer step, and"
                               " this one is a worker"]


def test_a_flow_with_two_reviewers_and_no_lens_loads_as_it_did():
    # personas: two reviewers told different things in their own files
    assert spec.check(two(lenses=(None, None))) == []


# what a run sends


def a_pair(tmp_path, monkeypatch, head=""):
    a_flow(tmp_path, monkeypatch, "pair", ["worker"])
    folder = tmp_path / "flows" / "pair"
    (folder / "flow.yaml").write_text(
        "name: pair\n" + head + "steps:\n"
        "  - role: worker\n    prompt: worker.md\n"
        "  - role: reviewer\n    prompt: reads.md\n    on_redo: worker\n"
        "    lens: " + SPEC_LENS + "\n"
        "  - role: reviewer\n    prompt: runs.md\n    on_redo: worker\n"
        "    lens: " + RUN_LENS + "\n" + CLAUDE, encoding="utf-8")
    for name in ("reads.md", "runs.md"):
        (folder / name).write_text("# reviewer\n", encoding="utf-8")


def prompts_of(cli):
    return [c["stdin"].decode("utf-8", "replace") for c in cli.calls]


OK = "VERDICT: ok\n\nfine\n"


def test_each_reviewer_is_told_its_lens_and_what_the_others_read_for(
        tmp_path, monkeypatch, fake_cli):
    a_pair(tmp_path, monkeypatch)
    cli = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nread it\n"),
                   answer(OK))
    assert engine.main() == 0
    worker, reads, runs = prompts_of(cli)
    # each reads the work, not the verdict of the one before it
    assert "did it" in runs and "read it" not in runs
    assert SPEC_LENS not in worker and RUN_LENS not in worker
    mine, others = reads.split("the others read for:")
    assert SPEC_LENS in mine and RUN_LENS in others.split("\n")[0]
    mine, others = runs.split("the others read for:")
    assert RUN_LENS in mine and SPEC_LENS in others.split("\n")[0]
    assert [l["step"] for l in every_line(tmp_path)] == \
        ["worker.md", "reads.md", "runs.md"]


def test_a_redo_from_either_reviewer_sends_the_work_back_and_both_read_it_again(
        tmp_path, monkeypatch, fake_cli):
    a_pair(tmp_path, monkeypatch)
    cli = fake_cli(answer("did it\n"), answer(OK),
                   answer("VERDICT: redo\n\nmul(0, 3) raises\n"),
                   answer("did it again\n"), answer(OK), answer(OK))
    assert engine.main() == 0
    assert len(cli.calls) == 6
    lines = every_line(tmp_path)
    assert [(l["step"], l["to"]) for l in lines] == [
        ("worker.md", "reads.md"), ("reads.md", "runs.md"),
        ("runs.md", "worker.md"), ("worker.md", "reads.md"),
        ("reads.md", "runs.md"), ("runs.md", None)]


def test_a_run_parked_between_the_reviewers_hands_the_second_the_work(
        tmp_path, monkeypatch, fake_cli):
    import sys as _sys

    a_pair(tmp_path, monkeypatch, head="max_calls: 2\n")
    cli = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nread it\n"),
                   answer(OK))
    assert engine.main() != 0
    [first] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    assert len(cli.calls) == 2
    monkeypatch.setattr(_sys, "argv", ["run.py", "pair", "--force",
                                       "--resume", first.name,
                                       "--max-calls", "10"])
    assert engine.main() == 0
    runs = prompts_of(cli)[2]
    assert RUN_LENS in runs.split("the others read for:")[0]
    assert "did it" in runs and "read it" not in runs


def test_one_reviewer_kept_by_the_count_is_sent_no_lens(
        tmp_path, monkeypatch, fake_cli):
    a_pair(tmp_path, monkeypatch, head="reviewers: 1\n")
    cli = fake_cli(answer("did it\n"), answer(OK))
    assert engine.main() == 0
    _, reads = prompts_of(cli)
    assert SPEC_LENS not in reads and "the others read for" not in reads


# the flow that ships with it


def test_build_feature_runs_two_reviewers_with_a_lens_each_by_default():
    raw = yaml.safe_load(open("flows/build-feature/flow.yaml",
                              encoding="utf-8"))
    loaded = spec.load(raw)
    reviewers = [s for s in loaded.steps if s["role"] == "reviewer"]
    assert raw.get("reviewers") == 2 and len(reviewers) == 2
    assert all(s.get("lens") and s.get("on_redo") == "worker"
               for s in reviewers)
    assert reviewers[0]["lens"] != reviewers[1]["lens"]
