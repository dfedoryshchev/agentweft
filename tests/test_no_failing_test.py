"""a step that cannot make the test fail parks with its reason.

fix-with-test's worker is told to say so and stop when the bug does not
show. with no `TEST:` and no `FAILS:` line, or each saying none, and a
HANDOFF `QUESTION:` that cites a line of a file in the place, the run parks
on that question on the first go: no send-back is spent and nothing is
patched. without such a question the red-test gate judges the answer as it
always has.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.providers import cli_provider, fake_provider
from agentweft.roles import resolver
from agentweft.runner import engine, prompts, resume, ruling, state

NL = chr(10)
RETRO = "retro.md"
FLOWS = Path(__file__).resolve().parents[1] / "flows"
WORKS = "def add(a, b):" + NL + "    return a + b" + NL
PASSES = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
          + "    assert add(1, 2) == 3" + NL)
# the gate reads the answer without its HANDOFF block, and an answer that is
# only a block reads to it as no answer at all
SAYS = "add(1, 2) gives 3 on this code, so no test was written." + NL + NL
ASKS = ("QUESTION: calc.py:2 already returns a + b, so add(1, 2) is 3. was"
        " the report about another input?" + NL
        + "RECOMMEND: close the report as not seen on this code" + NL)


def answer(top, question=ASKS):
    return (top + "HANDOFF" + NL + "DID:" + NL
            + "- no test written: add(1, 2) gives 3 on the code as it is" + NL
            + question + "END HANDOFF" + NL)


def run_it(tmp_path, monkeypatch, said, writes=None):
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "calc.py").write_text(WORKS, encoding="utf-8")
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if step == RETRO:
            return fake_provider.NOTHING_TO_KEEP, False
        if step == "worker.md" and writes:
            for rel, text in writes.items():
                (project / rel).write_text(text, encoding="utf-8")
        return said.get(step, ""), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "fix-with-test", "--force",
                                      "--flows", str(FLOWS),
                                      "--workdir", "project",
                                      "--task", "add(1, 2) returns -1"])
    code = engine.main()
    folder = next(p for p in (tmp_path / "runs").iterdir()
                  if (p / "manifest.json").exists())
    return code, asked, folder, project


def read(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def outcome(folder):
    return json.loads(read(folder / "manifest.json"))["outcome"]


def test_no_test_and_a_cited_question_parks_on_the_first_go(tmp_path,
                                                            monkeypatch):
    code, asked, folder, project = run_it(tmp_path, monkeypatch,
                                          {"worker.md": answer(SAYS)})
    assert asked[:2] != ["worker.md", "worker.md"], \
        "a send-back was spent on a step that could not make the test fail"
    assert outcome(folder) == "needs you: ruling", read(folder / "gates.md")
    question = read(folder / "question.md")
    assert "worker.md could not make a test fail, and asks: calc.py:2" \
        in question
    assert "- calc.py:2" in question
    assert "close the report as not seen on this code" in question
    assert "patcher.md" not in asked
    assert read(project / "calc.py") == WORKS


def test_a_test_line_saying_none_parks_the_same_way(tmp_path, monkeypatch):
    top = ("FAILS: none. add(1, 2) gives 3" + NL + "TEST: none written" + NL
           + NL)
    code, asked, folder, _ = run_it(tmp_path, monkeypatch,
                                    {"worker.md": answer(top)})
    assert asked.count("worker.md") == 1
    assert outcome(folder) == "needs you: ruling"
    assert "could not make a test fail" in read(folder / "question.md")


def test_no_test_and_no_question_is_still_sent_back(tmp_path, monkeypatch):
    code, asked, folder, _ = run_it(tmp_path, monkeypatch, {
        "worker.md": answer(SAYS, "QUESTION: none" + NL)})
    assert asked.count("worker.md") == 2
    assert outcome(folder) != "needs you: ruling"
    assert "FAIL red-test - no FAILS: line" in read(folder / "gates.md")


@pytest.mark.parametrize("question", [
    "QUESTION: was the report about another input?" + NL,
    "QUESTION: is gone.py:4 the place the report means?" + NL],
    ids=["no-cite", "no-such-file"])
def test_a_question_citing_no_line_in_the_place_is_still_sent_back(
        tmp_path, monkeypatch, question):
    code, asked, folder, _ = run_it(tmp_path, monkeypatch, {
        "worker.md": answer(SAYS, question)})
    assert asked.count("worker.md") == 2
    assert outcome(folder) != "needs you: ruling"


def test_a_named_test_that_passes_still_fails_red_test(tmp_path, monkeypatch):
    top = ("FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py" + NL
           + NL)
    code, asked, folder, _ = run_it(
        tmp_path, monkeypatch, {"worker.md": answer(top)},
        writes={"tests/test_calc.py": PASSES})
    assert outcome(folder) != "needs you: ruling"
    assert "the test passed before the patch" in read(folder / "gates.md")


def test_only_a_step_held_to_a_red_test_parks_this_way():
    fm = runner.config("fix-with-test")
    by_role = resolver.resolve(fm.raw, runner.flow_path("fix-with-test"))
    run = runner.Run("fix-with-test", fm, by_role)
    assert run.wants_red("worker.md")
    assert not run.wants_red("patcher.md")
    assert not run.wants_red("verify.md")


def test_the_question_is_read_from_the_handoff_with_its_cite(tmp_path):
    (tmp_path / "calc.py").write_text(WORKS, encoding="utf-8")
    said = ruling.no_red("worker.md", answer(SAYS), tmp_path)
    assert said.startswith("NEEDS: worker.md could not make a test fail")
    assert ruling.no_red("worker.md", "FAILS: assert 1" + NL + "TEST: t.py"
                         + NL + answer(SAYS), tmp_path) is None
