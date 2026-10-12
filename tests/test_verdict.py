"""a step told to answer with a verdict line, and what it actually answered.

the router acts on one word, redo, and everything else walked on. so a
reviewer that shouted `VERDICT: REDO`, or answered `VERDICT: maybe`, or forgot
the line, let the work through exactly as if it had said ok. a step that was
never asked for a verdict still goes on without one.
"""
import importlib
import sys

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.roles import resolver
from agentweft.runner import engine, prompts
from agentweft.runner.handoff import Handoff
from agentweft.runner.router import Router

NL = chr(10)
# the package hands out the function `config` under the module's own name
config = importlib.import_module("agentweft.runner.config")


@pytest.mark.parametrize("text, word", [
    ("VERDICT: REDO", "redo"),
    ("verdict: redo", "redo"),
    ("VERDICT:redo", "redo"),
    ("VERDICT: ok.", "ok"),
    ("VERDICT: Redo!", "redo"),
    (NL + NL + "  VERDICT: ok" + NL + "fine", "ok"),
    ("VERDICT: maybe", "maybe"),
    ("VERDICT: ok, but fix the title", "ok, but fix the title"),
])
def test_the_word_is_read_whatever_case_and_punctuation(text, word):
    assert config.verdict(text) == word
    assert config.verdict(text, asked=True) == word


@pytest.mark.parametrize("text", [
    "looks fine to me",
    "the work is fine" + NL + "VERDICT: ok",
    "VERDICT:",
    "",
])
def test_a_step_asked_for_a_verdict_has_none_unless_its_first_line_is_one(text):
    assert config.verdict(text, asked=True) == ""


def test_a_step_not_asked_has_no_verdict_line_and_still_goes_on():
    assert config.verdict("the work is fine" + NL + "VERDICT: redo") == "ok"


def own_prompt(flow, step, role):
    fm = runner.config(flow)
    by_role = resolver.resolve(fm.raw, runner.flow_path(flow))
    return prompts.load_prompt(flow, step, by_role[role], role)


def test_what_a_step_is_told_decides_whether_it_was_asked():
    assert config.asks_for_verdict(
        own_prompt("summarise-and-check", "reviewer.md", "reviewer"))
    assert not config.asks_for_verdict(
        own_prompt("summarise-and-check", "worker.md", "worker"))
    assert config.asks_for_verdict(resolver.role_prompt("judge.md"))
    assert not config.asks_for_verdict(resolver.role_prompt("verify.md"))


def test_naming_the_verdict_in_passing_is_not_asking_for_one():
    assert not config.asks_for_verdict(
        "the reviewer after you answers VERDICT: redo if this is wrong.")


def a_run(monkeypatch, reply):
    fm = runner.config("summarise-and-check")
    by_role = resolver.resolve(fm.raw, runner.flow_path("summarise-and-check"))
    return runner.Run("summarise-and-check", fm, by_role,
                      provider={"provider": "fake", "reply": reply})


def test_a_step_records_whether_it_was_asked(monkeypatch):
    reviewed = a_run(monkeypatch, "VERDICT: maybe").step("reviewer.md")
    assert reviewed.verdict == "maybe"
    assert reviewed.meta["asked"] is True
    worked = a_run(monkeypatch, "VERDICT: maybe").step("worker.md")
    assert worked.meta["asked"] is False


def asked(text, word):
    return Handoff("reviewer", text, word, meta={"asked": True})


def test_the_router_will_not_go_on_from_a_word_it_cannot_read():
    r = Router(runner.config("summarise-and-check"), cap=2)
    why = r.gate("reviewer.md", asked("VERDICT: maybe", "maybe"))
    assert '"maybe"' in why
    assert "reviewer.md" in why
    assert "no verdict line" in r.gate("reviewer.md", asked("fine", ""))
    assert r.gate("reviewer.md", asked("VERDICT: ok", "ok")) is None
    assert r.gate("reviewer.md", asked("VERDICT: redo", "redo")) is None


def test_the_router_leaves_a_step_that_was_not_asked_alone():
    r = Router(runner.config("summarise-and-check"), cap=2)
    assert r.gate("worker.md", Handoff("worker", "VERDICT: maybe",
                                       "maybe")) is None


@pytest.mark.parametrize("words, word", [
    (["ok", "ok"], "ok"),
    (["ok", "redo"], "redo"),
    (["redo", "maybe", "ok"], "maybe"),
    (["ok", ""], ""),
])
def test_one_task_of_a_fanned_out_step_speaks_for_all_of_them(words, word):
    parts = [Handoff("reviewer", "x", w, meta={"asked": True}) for w in words]
    assert engine.fanned_verdict(parts) == word


def a_flow(tmp_path, monkeypatch, name, review, fan=False):
    """a worker that answers and a reviewer that answers `review`, then a
    merge that only runs if the reviewer let the work through."""
    flow = tmp_path / "flows" / name
    flow.mkdir(parents=True)
    worker = '"- a.md | look at a\\n- b.md | look at b\\n"'
    body = ("name: " + name + NL
            + "steps:" + NL
            + "  - role: worker" + NL
            + "    provider:" + NL
            + "      provider: fake" + NL
            + "      reply: " + worker + NL
            + "  - role: reviewer" + NL
            + ("    fanout: true" + NL if fan else "")
            + "    provider:" + NL
            + "      provider: fake" + NL
            + "      reply: " + review + NL
            + "  - role: merge" + NL
            + "provider:" + NL
            + "  provider: fake" + NL)
    (flow / "flow.yaml").write_text(body, encoding="utf-8")
    (flow / "instructions.md").write_text("the " + name + " flow." + NL,
                                          encoding="utf-8")
    for role in ("worker", "reviewer", "merge"):
        (flow / (role + ".md")).write_text("# " + role + NL + NL + "do it."
                                           + NL, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force",
                                      "--flows", "flows"])
    engine.main()
    run_dir = sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())[-1]
    journal = (tmp_path / "runs" / "journal.md").read_text().strip().split(NL)
    return run_dir, journal[-1].split("  ")[2]


def test_a_shouted_redo_sends_the_work_back(tmp_path, monkeypatch):
    run_dir, status = a_flow(tmp_path, monkeypatch, "shouted",
                             '"VERDICT: REDO\\n\\nstill wrong\\n"')
    assert status == "parked at reviewer.md"
    assert not (run_dir / "merge.md").exists()


@pytest.mark.parametrize("name, review, said", [
    ("maybe", '"VERDICT: maybe\\n\\nnot sure\\n"', '"maybe"'),
    ("hedged", '"VERDICT: ok, mostly\\n"', '"ok, mostly"'),
    ("lineless", '"looks fine\\n"', "no verdict line"),
    ("buried", '"looks fine\\nVERDICT: ok\\n"', "no verdict line"),
])
def test_a_reviewer_the_router_cannot_read_fails_the_run(
        tmp_path, monkeypatch, capsys, name, review, said):
    run_dir, status = a_flow(tmp_path, monkeypatch, name, review)
    assert status == "failed at reviewer.md"
    assert not (run_dir / "merge.md").exists()
    assert said in capsys.readouterr().out


def test_an_empty_review_is_not_an_approval(tmp_path, monkeypatch):
    real = engine.call

    def silent_reviewer(prompt, **kw):
        if prompt.startswith("# reviewer"):
            return "", False
        return real(prompt, **kw)

    monkeypatch.setattr(engine, "call", silent_reviewer)
    run_dir, status = a_flow(tmp_path, monkeypatch, "silent",
                             '"VERDICT: ok\\n"')
    assert status == "failed at reviewer.md"
    assert not (run_dir / "merge.md").exists()


def test_a_fanned_out_reviewer_the_router_cannot_read_fails_the_run(
        tmp_path, monkeypatch, capsys):
    run_dir, status = a_flow(tmp_path, monkeypatch, "fan-maybe",
                             '"VERDICT: maybe\\n"', fan=True)
    assert status == "failed at reviewer.md"
    assert not (run_dir / "merge.md").exists()
    assert '"maybe"' in capsys.readouterr().out


def test_a_fanned_out_redo_sends_the_work_back(tmp_path, monkeypatch):
    run_dir, status = a_flow(tmp_path, monkeypatch, "fan-redo",
                             '"VERDICT: redo\\n\\nstill wrong\\n"', fan=True)
    assert status == "parked at reviewer.md"
    assert not (run_dir / "merge.md").exists()


def test_a_reviewer_that_approves_lets_the_work_through(tmp_path, monkeypatch):
    run_dir, status = a_flow(tmp_path, monkeypatch, "approved",
                             '"VERDICT: Ok.\\n\\nfine\\n"', fan=True)
    assert status == "ok"
    assert (run_dir / "merge.md").exists()
