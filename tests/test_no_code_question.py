"""a question whose answer changes no code is the step's call, not a stop.

a `NEEDS:` whose `SIZE:` says no code changes either way rides in the
handoff as a doubt, with its `RECOMMEND:` as the answer taken, and the step
goes on through its gates. one that names code still parks; when the step
changed the tree before it asked, its gates run on that first, and the park
says the work was done and then asked about.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, handoff, prompts, ruling, stops

NL = chr(10)
PASS = [sys.executable, "-c", "pass"]
FAIL = [sys.executable, "-c", "import sys; sys.exit(1)"]
ORDER = "which error is reported first when both happen?"
NO_CODE = ("NEEDS: " + ORDER + NL + "RECOMMEND: the date error first, the"
           " way parse() already checks it" + NL
           + "SIZE: zero code lines" + NL)
CODE = ("NEEDS: " + ORDER + NL + "RECOMMEND: the amount error first" + NL
        + "SIZE: 3 lines in calc.py" + NL)
BLOCK = (NL + "HANDOFF" + NL + "DID:" + NL + "- fixed the check" + NL
         + "DOUBTS:" + NL + "- none" + NL + "END HANDOFF" + NL)


def a_flow(tmp_path, monkeypatch, gate=PASS):
    d = tmp_path / "flows" / "ask"
    d.mkdir(parents=True)
    body = ("name: ask" + NL + "spec_files: read-only" + NL + "steps:" + NL
            + "  - role: a" + NL + "    prompt: a.md" + NL + "    gates:" + NL
            + "      - gate: command" + NL + "        command: "
            + json.dumps(gate) + NL + "  - role: b" + NL + "    prompt: b.md"
            + NL)
    for role in ("a", "b"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "TASK.md").write_text("# task" + NL + "dates are checked"
                                      + NL, encoding="utf-8")
    (tmp_path / "calc.py").write_text("x = 1" + NL, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])


def answering(monkeypatch, tmp_path, first, writes=None):
    """step a answers `first` once, leaving `writes` in the place."""
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if step == "a.md" and asked.count("a.md") == 1:
            for rel, text in (writes or {}).items():
                (tmp_path / rel).write_text(text, encoding="utf-8")
            return first, False
        return "done by " + step + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "ask", "--force"])
    return engine.main()


def folder(tmp_path):
    [found] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    return found


def gated(found):
    path = found / "gates.md"
    return "## a.md" in path.read_text(encoding="utf-8") \
        if path.exists() else False


def test_a_size_that_names_no_code_is_read_as_no_code():
    for size in ("zero code lines", "Zero code lines.", "none", "0 lines",
                 "No code change, if month-first is confirmed",
                 "no code", "one test", "one test only", "nothing"):
        assert ruling.no_code(size), size
    for size in ("3 lines in calc.py", "one line in parse.py", "",
                 "no code change for A, 4 lines for B", "a test and 2 lines",
                 "small"):
        assert not ruling.no_code(size), size


def test_a_question_that_changes_no_code_becomes_a_doubt(tmp_path,
                                                         monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, tmp_path, "fixed it" + NL + NO_CODE + BLOCK,
                      {"calc.py": "x = 2" + NL})
    assert run(monkeypatch) == stops.EXIT_OK
    assert asked == ["a.md", "b.md"]
    found = folder(tmp_path)
    assert gated(found)
    said = (found / "a.md").read_text(encoding="utf-8")
    assert "NEEDS:" not in said and "SIZE:" not in said
    [doubt] = handoff.parse(said)["doubts"]
    assert ORDER[:-1] in doubt and "the date error first" in doubt
    assert "zero code lines" in doubt
    raw = (found / "a.asked.md").read_text(encoding="utf-8")
    assert raw == "fixed it" + NL + NO_CODE + BLOCK
    text = (found / "handoff.md").read_text(encoding="utf-8")
    assert "the date error first" in text


def test_a_step_that_changed_the_tree_runs_its_gates_before_the_stop(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch)
    answering(monkeypatch, tmp_path, "fixed it" + NL + CODE,
              {"calc.py": "x = 2" + NL})
    assert run(monkeypatch) == stops.EXIT_STOP
    found = folder(tmp_path)
    assert gated(found)
    printed = capsys.readouterr().out
    assert "instead of doing the work" not in printed
    assert "a.md did the work, then asked for a ruling" in printed
    text = (found / "handoff.md").read_text(encoding="utf-8")
    assert "its gates ran on what it changed, and passed" in text


def test_a_stop_after_failed_gates_says_they_failed(tmp_path, monkeypatch,
                                                     capsys):
    a_flow(tmp_path, monkeypatch, gate=FAIL)
    answering(monkeypatch, tmp_path, "fixed it" + NL + CODE,
              {"calc.py": "x = 2" + NL})
    assert run(monkeypatch) == stops.EXIT_STOP
    found = folder(tmp_path)
    assert gated(found)
    lines = (tmp_path / "runs" / "journal.md").read_text(
        encoding="utf-8").split(NL)
    end = stops.read([l for l in lines if l.strip()][-1])
    assert end.status == "parked at a.md"
    text = (found / "handoff.md").read_text(encoding="utf-8")
    assert "its gates ran on what it changed, and failed: command" in text


def test_a_question_that_names_code_still_parks_ungated(tmp_path, monkeypatch,
                                                        capsys):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, tmp_path, CODE)
    assert run(monkeypatch) == stops.EXIT_STOP
    assert asked == ["a.md"]
    found = folder(tmp_path)
    assert not gated(found)
    assert ORDER in (found / "question.md").read_text(encoding="utf-8")
    assert "asked for a ruling instead of doing the work" in \
        capsys.readouterr().out
    text = (found / "handoff.md").read_text(encoding="utf-8")
    decision = text.split("## the one decision")[1].split("##")[0]
    assert ORDER in decision


def test_the_fix_steps_are_told_the_order_of_two_errors_is_theirs():
    line = ("the order of two errors the spec does not fix is yours; follow"
            " the code's convention and say so under ASSUMED")
    for name in ("worker.md", "patcher.md"):
        with open("flows/fix-with-test/" + name, encoding="utf-8") as f:
            assert line in " ".join(f.read().split()), name


def test_a_demoted_question_lands_under_doubts_whatever_the_block_holds():
    asked = "the fix" + NL + NO_CODE
    for tail, before in (
            (BLOCK, []),
            (BLOCK.replace("DOUBTS:" + NL + "- none", "DOUBTS: a caller"),
             ["a caller"]),
            (BLOCK.replace("DOUBTS:" + NL + "- none" + NL, ""), []),
            (BLOCK.replace("DOUBTS:", "- DOUBTS:"), []),
            (BLOCK.replace("- none" + NL + "END", "- note: a caller" + NL
                           + "END"), ["note: a caller"])):
        said, doubt = ruling.demoted(asked + tail)
        assert "NEEDS:" not in said and "RECOMMEND:" not in said
        assert handoff.parse(said)["doubts"] == before + [doubt]
        assert handoff.parse(said)["did"] == ["fixed the check"]
    said, doubt = ruling.demoted(asked)
    assert said == "the fix" + NL + "DOUBTS: " + doubt + NL


def test_a_question_with_no_pick_or_a_size_in_code_is_not_demoted():
    assert ruling.demoted("NEEDS: " + ORDER + NL + "SIZE: zero" + NL) is None
    assert ruling.demoted(CODE) is None
    assert ruling.demoted("all done" + NL) is None


def test_a_block_questions_pick_does_not_demote_the_stop_question():
    said = ("NEEDS: is a blank amount zero or an error?" + NL + NL + "HANDOFF"
            + NL + "QUESTION: should the banner be blue?" + NL
            + "RECOMMEND: yes, blue" + NL + "SIZE: zero code lines" + NL
            + "END HANDOFF" + NL)
    assert ruling.demoted(said) is None


def asking(recommend, size):
    return ("did the fix" + NL + "NEEDS: " + ORDER + NL + "RECOMMEND: "
            + recommend + NL + "SIZE: " + size + NL)


PRICED_ON_THE_OTHER = (
    ("leave it as it is", "one line in export.py, plus a unit test."),
    ("leave it as it is.", "none if left; one line in importer.py plus a test"
     " if a lone CR should count as a line ending."),
    ("keep it as part of the field", "none if kept; one line in importer.py if"
     " it is ruled a line break."),
    ("month first, the way parse() reads it now", "one test; no code change"),
    ("month first, the way parse() reads it now", "one test, no code change"),
    ("month first, the way parse() reads it now", "one test. No code change,"
     " if month-first is confirmed"))


def test_a_question_whose_recommended_answer_changes_no_code_is_demoted():
    for recommend, size in PRICED_ON_THE_OTHER:
        found = ruling.demoted(asking(recommend, size))
        assert found is not None, size
        said, doubt = found
        assert "NEEDS:" not in said and recommend in doubt, size


def test_a_question_whose_recommended_branch_names_code_still_parks():
    for recommend, size in (
            ("count a lone CR as a line ending", "none if left; one line in"
             " importer.py plus a test if a lone CR should count as a line"
             " ending."),
            ("rule it a line break", "none if kept; one line in importer.py"
             " if it is ruled a line break."),
            ("raise when it is called directly", "one line in export.py,"
             " plus a unit test."),
            ("day first", "2 lines in parse.py if day-first is ruled; one test"
             " if month-first is confirmed"),
            ("the amount error first", "3 lines in calc.py")):
        assert ruling.demoted(asking(recommend, size)) is None, size


def test_a_question_that_cites_a_spec_line_is_not_demoted():
    said = ("NEEDS: TASK.md:3 says totals are rounded; is 2.5 rounded up or"
            " down?" + NL + "CITES: TASK.md:3" + NL + "RECOMMEND: down" + NL
            + "SIZE: one test" + NL)
    assert ruling.demoted(said) is None
