"""a step that cannot decide asks, and the run waits for the answer.

`NEEDS: <question>` (or `VERDICT: park`) in a step's answer parks the run
before that step's gates, waiting for a ruling. `--resume <id> --answer` runs
that same step again with the answer at the end of its prompt and writes the
question and the answer to decisions.md. `REFUSED:` with a cited spec line is
a finished run, not a failed one.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import engine, prompts, stops

NL = chr(10)
FAIL = [sys.executable, "-c", "import sys; sys.exit(1)"]
QUESTION = "keep amounts as strings, or make them numbers?"
ASKS = ("NEEDS: " + QUESTION + NL + "CITES:" + NL
        + "- TASK.md:2 - amounts are strings" + NL)


def a_flow(tmp_path, monkeypatch, name="ask", gated=True):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + NL + "steps:" + NL
    for role in ("a", "b"):
        body = body + "  - role: " + role + NL + "    prompt: " + role + ".md" + NL
        if role == "a" and gated:
            body = (body + "    gates:" + NL + "      - gate: command" + NL
                    + "        command: " + json.dumps(FAIL) + NL)
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "TASK.md").write_text(
        "# task" + NL + "amounts are strings with 2 decimals" + NL,
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    return d


def asking(monkeypatch, first):
    """step a answers `first` until it is told a ruling, then plain work."""
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        if step == "a.md" and "RULING" not in prompt:
            return first, False
        return "done by " + step + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run.py"] + list(argv))
    return engine.main()


def folders(tmp_path):
    runs = tmp_path / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() \
        else []


def journal(tmp_path):
    return [l for l in (tmp_path / "runs" / "journal.md")
            .read_text(encoding="utf-8").split(NL) if l.strip()]


def end(tmp_path):
    return stops.read(journal(tmp_path)[-1])


def test_a_needs_line_parks_before_the_steps_gates_run(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = asking(monkeypatch, ASKS)
    assert run(monkeypatch, "ask", "--force") == stops.EXIT_STOP
    [folder] = folders(tmp_path)
    line = end(tmp_path)
    assert line.status == "parked at a.md" and line.cause == stops.PARKED
    assert [s for s, _ in asked] == ["a.md"]
    # the gate would have failed: it never ran, so the stop is the question
    assert "## a.md" not in (folder / "gates.md").read_text(encoding="utf-8") \
        if (folder / "gates.md").exists() else True
    kept = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert kept["steps"][0]["state"] == "parked for a ruling"
    assert kept["outcome"] == "needs you: ruling"
    assert "kind       ruling" in (folder / "why.md").read_text(encoding="utf-8")
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    assert QUESTION in handoff and "--answer" in handoff
    assert QUESTION in (folder / "question.md").read_text(encoding="utf-8")


def test_an_answer_runs_that_step_again_with_the_answer_last(tmp_path,
                                                             monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = asking(monkeypatch, ASKS)
    run(monkeypatch, "ask", "--force")
    [first] = folders(tmp_path)
    asked.clear()
    # the gate on a now passes, so the resumed run can finish
    (tmp_path / "flows" / "ask" / "flow.yaml").write_text(
        "name: ask" + NL + "steps:" + NL + "  - role: a" + NL
        + "    prompt: a.md" + NL + "  - role: b" + NL + "    prompt: b.md"
        + NL, encoding="utf-8")
    assert run(monkeypatch, "ask", "--force", "--resume", first.name,
               "--answer", "numbers, as JSON numbers") == stops.EXIT_OK
    assert [s for s, _ in asked] == ["a.md", "b.md"]
    prompt = asked[0][1]
    assert prompt.rstrip().endswith("numbers, as JSON numbers")
    assert QUESTION in prompt
    [ruled] = decisions.read(tmp_path)
    assert "numbers, as JSON numbers" in ruled.decided
    assert QUESTION in ruled.why and "answered by" in ruled.why
    assert end(tmp_path).status == "ok (resumed)"


def test_an_answer_can_come_from_a_file(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, gated=False)
    asked = asking(monkeypatch, ASKS)
    run(monkeypatch, "ask", "--force")
    [first] = folders(tmp_path)
    (tmp_path / "ruling.txt").write_text("keep them strings" + NL,
                                         encoding="utf-8")
    asked.clear()
    assert run(monkeypatch, "ask", "--force", "--resume", first.name,
               "--answer-file", "ruling.txt") == stops.EXIT_OK
    assert asked[0][1].rstrip().endswith("keep them strings")
    assert "keep them strings" in decisions.read(tmp_path)[0].decided


def test_a_resume_without_an_answer_refuses_and_prints_the_question(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch)
    asked = asking(monkeypatch, ASKS)
    run(monkeypatch, "ask", "--force")
    [first] = folders(tmp_path)
    before = journal(tmp_path)
    asked.clear()
    capsys.readouterr()
    assert run(monkeypatch, "ask", "--force", "--resume",
               first.name) == stops.EXIT_STOP
    printed = capsys.readouterr().out
    assert QUESTION in printed and "--answer" in printed
    assert asked == []
    assert journal(tmp_path) == before
    assert folders(tmp_path) == [first]


def test_verdict_park_asks_too(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asking(monkeypatch, "VERDICT: park" + NL + NL + "which file is the spec?"
           + NL)
    assert run(monkeypatch, "ask", "--force") == stops.EXIT_STOP
    [folder] = folders(tmp_path)
    assert end(tmp_path).status == "parked at a.md"
    assert "which file is the spec?" in (folder / "question.md").read_text(
        encoding="utf-8")


def test_a_refusal_that_cites_the_spec_is_a_finished_run(tmp_path,
                                                         monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch)
    asked = asking(monkeypatch, 'REFUSED: TASK.md:2 "amounts are strings with'
                   ' 2 decimals"' + NL)
    assert run(monkeypatch, "ask", "--force") == stops.EXIT_OK
    [folder] = folders(tmp_path)
    line = end(tmp_path)
    assert line.status == "refused at a.md"
    assert stops.outcome(line.cause) == "refused (spec cited)"
    assert [s for s, _ in asked] == ["a.md"]
    first = (folder / "handoff.md").read_text(encoding="utf-8").split(NL)[0]
    assert first.startswith("# ask " + folder.name
                            + ": refused (spec cited) at a.md")
    kept = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert kept["outcome"] == "refused (spec cited)"


def test_a_refusal_with_no_cite_is_read_as_a_question(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asking(monkeypatch, "REFUSED: I do not think this is a good idea" + NL)
    assert run(monkeypatch, "ask", "--force") == stops.EXIT_STOP
    [folder] = folders(tmp_path)
    assert end(tmp_path).status == "parked at a.md"
    assert "good idea" in (folder / "question.md").read_text(encoding="utf-8")


def test_a_cite_of_a_line_that_is_not_there_is_no_cite(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asking(monkeypatch, 'REFUSED: TASK.md:40 "amounts are strings"' + NL)
    assert run(monkeypatch, "ask", "--force") == stops.EXIT_STOP
    assert end(tmp_path).status == "parked at a.md"


def test_a_refusal_quoting_what_its_line_does_not_say_fails_the_step(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, gated=False)
    asked = asking(monkeypatch, 'REFUSED: TASK.md:2 "amounts are floats"' + NL)
    assert run(monkeypatch, "ask", "--force") != stops.EXIT_OK
    [folder] = folders(tmp_path)
    assert [s for s, _ in asked] == ["a.md", "a.md"]
    assert end(tmp_path).cause != stops.DECLINED
    gates = (folder / "gates.md").read_text(encoding="utf-8")
    assert "FAIL quote" in gates and '"amounts are floats"' in gates


def test_a_needs_inside_a_code_fence_is_not_a_question(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, gated=False)
    asked = asking(monkeypatch, "here is the test" + NL + "```" + NL
                   + "assert said == 'NEEDS: x'" + NL + "NEEDS: x" + NL
                   + "```" + NL)
    assert run(monkeypatch, "ask", "--force") == stops.EXIT_OK
    assert [s for s, _ in asked] == ["a.md", "b.md"]


def test_an_answer_to_a_run_that_asked_nothing_is_refused(tmp_path,
                                                          monkeypatch, capsys):
    d = a_flow(tmp_path, monkeypatch, gated=False)
    (d / "flow.yaml").write_text(
        "name: ask" + NL + "steps:" + NL + "  - role: a" + NL
        + "    prompt: a.md" + NL + "    pause: user" + NL + "  - role: b"
        + NL + "    prompt: b.md" + NL, encoding="utf-8")
    asked = asking(monkeypatch, "plain work" + NL)
    run(monkeypatch, "ask", "--force")
    [first] = folders(tmp_path)
    asked.clear()
    assert run(monkeypatch, "ask", "--force", "--resume", first.name,
               "--answer", "yes") == 1
    assert asked == []
    assert "not waiting for a ruling" in capsys.readouterr().out


def test_the_patcher_is_told_to_ask_when_the_test_and_the_code_disagree():
    with open("flows/fix-with-test/patcher.md", encoding="utf-8") as f:
        text = f.read()
    assert ("if the test and the code disagree about what is right, answer"
            " NEEDS: <the question> and stop") in " ".join(text.split())


def test_a_step_refusing_is_its_own_cause_and_exits_clean():
    assert stops.outcome(stops.DECLINED) == "refused (spec cited)"
    assert stops.exit_code(stops.DECLINED) == stops.EXIT_OK
    assert stops.status(stops.DECLINED, "a.md") == "refused at a.md"
