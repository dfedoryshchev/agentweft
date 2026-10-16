"""a score is kept with what produced it, and two scores produced differently
are an A/B, not a regression.

a model swap scored against last week's model used to print BETTER or WORSE as
if the prompt had changed, which is the one thing the comparison exists to say.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.evals import __main__ as evals_main
from agentweft.evals import harness
from agentweft.providers import Provider, Reply, base
from agentweft.runner import prompts

REPO = Path(__file__).resolve().parent.parent
FLOW = "weekly-digest"
DIGEST = ("VERDICT: ok\n\n## what changed\n- a.md | changed | x\n\n"
          "## needs me\n- b.md | needs-me | y\n")
PLAN = ("TASK: a.md\nLIST: changed\nWHY: x\nFILES:\n- a.md\n\n"
        "TASK: b.md\nLIST: needs-me\nWHY: y\nFILES:\n- b.md\n")


class Modelled(Provider):
    """answers like the fake, the planner with a plan, and says which model
    answered."""

    name = "modelled"

    def at(self, step, task):
        self.step = step

    def ask(self, prompt, timeout=None):
        said = PLAN if getattr(self, "step", None) == "planner.md" \
            else self.opts.get("reply", DIGEST)
        return Reply(said, model=self.opts.get("model"))


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setitem(base.registry, Modelled.name, Modelled)
    flows = tmp_path / "flows"
    shutil.copytree(REPO / "flows" / FLOW, flows / FLOW)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    evals = tmp_path / "evals"
    monkeypatch.setattr(harness, "ROOT", evals)
    monkeypatch.setattr(harness, "LAST", evals / ".last.json")
    return tmp_path


def a_case(root, model="m-1", reply=DIGEST):
    case = root / "evals" / FLOW / "cases" / "two-files"
    if not (case / "inbox").exists():
        shutil.copytree(REPO / "evals" / FLOW / "cases" / "busy-week"
                        / "inbox", case / "inbox")
    (case / "case.yaml").write_text(yaml.safe_dump(
        {"inbox": "inbox",
         "provider": {"provider": "modelled", "model": model, "reply": reply},
         "expect": {"invariants": "all"}}), encoding="utf-8")
    return case


def flow_file(root):
    return root / "flows" / FLOW / "flow.yaml"


def edit_flow(root, change):
    path = flow_file(root)
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(spec)
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")


def scored_line(monkeypatch, capsys):
    """-> the case's line under "since the last scored run"."""
    monkeypatch.setattr(sys, "argv", ["evals", FLOW])
    evals_main.main()
    out = capsys.readouterr().out
    since = out.split("since the last scored run:")[1]
    return next((l for l in since.split("\n")
                 if l.strip().startswith("two-files")), since)


def test_a_score_is_kept_with_the_model_and_the_prompts_that_produced_it(
        root, monkeypatch, capsys):
    a_case(root, model="m-1")
    scored_line(monkeypatch, capsys)
    kept = json.loads(harness.LAST.read_text(encoding="utf-8"))
    key = kept[FLOW]["two-files"].get("key")
    assert key is not None
    assert key["models"]["planner.md"] == "modelled m-1"
    assert key["models"]["worker.md"] == "modelled m-1"
    assert len(key["prompts"]) == 64
    assert len(key["flow"]) == 64
    assert key["investigate"] == "off"
    assert key["verify"] == "off"
    assert key["date"]


def test_the_table_says_what_produced_each_score(root, monkeypatch, capsys):
    a_case(root, model="m-1")
    monkeypatch.setattr(sys, "argv", ["evals", FLOW, "--no-save"])
    evals_main.main()
    out = capsys.readouterr().out
    assert "      by modelled m-1 at every step, prompts " in out


def test_a_different_model_is_an_a_b_and_not_a_change_in_the_score(
        root, monkeypatch, capsys):
    a_case(root, model="m-1")
    scored_line(monkeypatch, capsys)
    a_case(root, model="m-2", reply=DIGEST + "\nhere is the digest\n")
    line = scored_line(monkeypatch, capsys)
    assert "A/B on model" in line
    assert "WORSE" not in line and "BETTER" not in line and "same" not in line
    assert " -> " in line


def test_an_edited_prompt_is_an_a_b_on_the_prompts(root, monkeypatch, capsys):
    a_case(root)
    scored_line(monkeypatch, capsys)
    planner = root / "flows" / FLOW / "planner.md"
    planner.write_text(planner.read_text(encoding="utf-8")
                       + "\nkeep it short.\n", encoding="utf-8")
    line = scored_line(monkeypatch, capsys)
    assert "A/B on prompts" in line
    assert "same" not in line


def test_turning_investigate_on_is_an_a_b_on_investigate(root, monkeypatch,
                                                          capsys):
    a_case(root)
    scored_line(monkeypatch, capsys)
    edit_flow(root, lambda spec: spec.update(investigate="cause"))
    line = scored_line(monkeypatch, capsys)
    assert "A/B on investigate" in line
    assert "WORSE" not in line and "same" not in line


def test_adding_a_verify_judge_is_an_a_b_on_verify(root, monkeypatch, capsys):
    a_case(root)
    scored_line(monkeypatch, capsys)
    shutil.copy(root / "flows" / FLOW / "reviewer.md",
                root / "flows" / FLOW / "verify.md")
    edit_flow(root, lambda spec: spec["steps"].append(
        {"role": "verify", "prompt": "verify.md"}))
    line = scored_line(monkeypatch, capsys)
    assert "A/B on verify" in line
    assert "WORSE" not in line and "BETTER" not in line


def test_the_same_model_and_prompts_still_compare(root, monkeypatch, capsys):
    a_case(root)
    scored_line(monkeypatch, capsys)
    a_case(root, reply=DIGEST + "\nhere is the digest\n")
    line = scored_line(monkeypatch, capsys)
    assert "WORSE" in line
    assert "A/B" not in line


def test_a_score_kept_before_the_key_existed_still_compares(root, monkeypatch,
                                                             capsys):
    a_case(root)
    harness.ROOT.mkdir(parents=True, exist_ok=True)
    harness.LAST.write_text(json.dumps({FLOW: {"two-files": {
        "passed": 4, "checked": 4, "calls": 5, "tokens": 0}}}),
        encoding="utf-8")
    line = scored_line(monkeypatch, capsys)
    assert "same" in line


def run(monkeypatch, capsys, *flags):
    monkeypatch.setattr(sys, "argv", ["evals", FLOW, *flags])
    code = evals_main.main()
    return code, capsys.readouterr().out


WORSE_REPLY = DIGEST + "\nhere is the digest\n"


def test_a_worse_score_under_the_same_key_fails_and_keeps_the_baseline(
        root, monkeypatch, capsys):
    a_case(root)
    assert run(monkeypatch, capsys)[0] == 0
    baseline = harness.LAST.read_text(encoding="utf-8")
    a_case(root, reply=WORSE_REPLY)
    code, out = run(monkeypatch, capsys)
    assert code == 1
    assert "two-files: scored worse" in out
    assert "not saved" in out
    assert harness.LAST.read_text(encoding="utf-8") == baseline


def test_a_worse_score_on_an_a_b_does_not_fail_and_says_so(
        root, monkeypatch, capsys):
    a_case(root, model="m-1")
    run(monkeypatch, capsys)
    a_case(root, model="m-2", reply=WORSE_REPLY)
    code, out = run(monkeypatch, capsys)
    assert code == 0
    assert "an A/B never fails the command" in out
    kept = json.loads(harness.LAST.read_text(encoding="utf-8"))
    assert kept[FLOW]["two-files"]["key"]["models"]["planner.md"] == \
        "modelled m-2"


def test_the_same_or_a_better_score_passes(root, monkeypatch, capsys):
    a_case(root, reply=WORSE_REPLY)
    run(monkeypatch, capsys)
    assert run(monkeypatch, capsys)[0] == 0
    a_case(root)
    code, out = run(monkeypatch, capsys)
    assert code == 0
    assert "BETTER" in out
    assert "scored worse" not in out


def test_accept_keeps_a_worse_score_as_the_new_baseline(root, monkeypatch,
                                                        capsys):
    a_case(root)
    run(monkeypatch, capsys)
    a_case(root, reply=WORSE_REPLY)
    assert run(monkeypatch, capsys, "--accept")[0] == 0
    assert run(monkeypatch, capsys)[0] == 0


def test_a_worse_score_with_no_save_still_fails(root, monkeypatch, capsys):
    a_case(root)
    run(monkeypatch, capsys)
    a_case(root, reply=WORSE_REPLY)
    assert run(monkeypatch, capsys, "--no-save")[0] == 1


def test_a_flow_with_no_cases_fails(root, monkeypatch, capsys):
    code, out = run(monkeypatch, capsys)
    assert code == 1
    assert "no cases under evals/" + FLOW + "/cases" in out
