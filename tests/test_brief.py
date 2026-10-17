"""the run keeps a brief: what the steps so far found, with the lines they
read quoted, handed to every later step so it does not open them again."""
import subprocess
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine
from test_stops import CLAUDE, a_flow, answer, the_folder

# about 2k tokens at 4 characters a token
CAP = 8000


def a_repo(where, lines=None):
    where.mkdir(parents=True)
    run = ["git", "-C", str(where)]
    subprocess.run(run + ["init", "-q"], check=True)
    subprocess.run(run + ["config", "user.email", "t@t"], check=True)
    subprocess.run(run + ["config", "user.name", "t"], check=True)
    (where / "calc.py").write_text(
        "def add(a, b):\n    return a - b  # kept-quote-marker\n",
        encoding="utf-8")
    (where / "TASK.md").write_text(
        "# task\n\nadd adds, and never rounds.\n", encoding="utf-8")
    if lines:
        (where / "big.py").write_text(
            "".join("value_%04d = %d  # filler text to make it wide\n" % (n, n)
                    for n in range(lines)), encoding="utf-8")
    subprocess.run(run + ["add", "."], check=True)
    subprocess.run(run + ["commit", "-qm", "start"], check=True)
    return where


def block(read, verified=True):
    out = "found it\n\nHANDOFF\nDID:\n- calc.py: add subtracts, the cause\n"
    if verified:
        out = out + ("VERIFIED:\n- add(2, 1) gives 1\n"
                     "  cmd: python -c \"import calc; print(calc.add(2, 1))\"\n"
                     "  saw: 1\n")
    return (out + "MUST NOT MISS:\n- TASK.md:3 - add adds\n"
            "READ:\n" + "".join("- " + r + "\n" for r in read)
            + "END HANDOFF\n")


def test_a_step_gets_the_steps_before_it_and_a_later_go_replaces_the_first(
        tmp_path):
    from agentweft.runner import brief, handoff

    place = a_repo(tmp_path / "repo")
    (tmp_path / "secret.txt").write_text("outside\n", encoding="utf-8")
    notes = brief.Brief(place, ["planner.md", "worker.md", "reviewer.md"])
    notes.add("planner.md", None, "planner", handoff.parse(
        block(["calc.py:2 - the minus", "../secret.txt:1 - out of the place"],
              verified=False)))
    notes.add("reviewer.md", None, "reviewer", handoff.parse(
        block(["TASK.md:1 - the title"], verified=False)))
    worker = notes.text("worker.md")
    assert "kept-quote-marker" in worker
    assert "the title" not in worker
    assert "outside" not in worker.replace("out of the place", "")
    assert notes.text("planner.md") == ""

    notes.add("planner.md", None, "planner", handoff.parse(
        block(["TASK.md:3 - the rule"], verified=False)))
    again = notes.text("worker.md")
    assert "the minus" not in again and "the rule" in again


def test_a_windows_path_and_a_non_ascii_line_are_quoted(tmp_path):
    from agentweft.runner import brief, handoff

    place = tmp_path / "repo"
    (place / "sub").mkdir(parents=True)
    (place / "sub" / "names.py").write_text(
        "CITY = \"Kyiv\"\nCAFE = \"caf\u00e9\"  # accent kept\n",
        encoding="utf-8")
    notes = brief.Brief(place, ["planner.md", "worker.md"])
    notes.add("planner.md", None, "planner", handoff.parse(
        block(["sub\\names.py:2 - the accented name",
               "..\\elsewhere\\names.py:1 - not in the place"],
              verified=False)))
    worker = notes.text("worker.md")
    assert "2: CAFE = \"caf\u00e9\"  # accent kept" in worker
    assert "Kyiv" not in worker


def prompts_of(cli):
    return [c["stdin"].decode("utf-8", "replace") for c in cli.calls]


def run_two(tmp_path, monkeypatch, fake_cli, first, lines=None,
            steps=("reader", "worker"), head=""):
    place = a_repo(tmp_path / "repo", lines)
    a_flow(tmp_path, monkeypatch, "two", list(steps),
           tail=head + "workdir: " + place.as_posix() + "\n" + CLAUDE)
    cli = fake_cli(answer(first, session="i-1"),
                   answer(block(["calc.py:1-2 - add subtracts"],
                                verified=False), session="w-1"))
    assert engine.main() == 0
    return prompts_of(cli), the_folder()


def test_a_second_step_starts_from_the_lines_the_first_one_quoted(
        tmp_path, monkeypatch, fake_cli):
    sent, folder = run_two(tmp_path, monkeypatch, fake_cli,
                           block(["calc.py:1-2 - add subtracts"]))
    kept = folder / "brief.md"
    assert kept.is_file(), "the run keeps no brief"
    brief = kept.read_text(encoding="utf-8")
    assert "return a - b  # kept-quote-marker" in brief
    assert "add adds, and never rounds." in brief
    assert "add(2, 1) gives 1" in brief
    assert len(brief) <= CAP

    first, second = sent
    assert "kept-quote-marker" not in first
    assert "return a - b  # kept-quote-marker" in second
    assert "add subtracts" in second.split("kept-quote-marker")[0]
    assert "add adds, and never rounds." in second
    start = second.index("kept-quote-marker")
    assert "start from" in second[:start].lower()


def test_the_brief_stays_under_its_cap_however_much_was_read(
        tmp_path, monkeypatch, fake_cli):
    read = ["big.py:%d-%d - the value set %d" % (n * 10 + 1, n * 10 + 10, n)
            for n in range(80)]
    sent, folder = run_two(tmp_path, monkeypatch, fake_cli, block(read),
                           lines=800)
    kept = folder / "brief.md"
    assert kept.is_file(), "the run keeps no brief"
    brief = kept.read_text(encoding="utf-8")
    assert len(brief) <= CAP, len(brief)
    assert "value_0000 = 0" in brief
    assert "left out" in brief

    second = sent[1]
    assert "value_0000 = 0" in second
    # what the brief adds to the prompt is measured, not assumed
    start = second.index("what the steps before you found.")
    end = second.index("end your answer with a handoff block", start)
    assert 0 < len(second[start:end].strip()) <= CAP


def briefed(prompt):
    from agentweft.runner.brief import NONE_YET

    return any(words in prompt for words in (
        "the brief below is what the steps before you found",
        "what the steps before you found.", NONE_YET))


def test_a_flow_with_the_brief_off_starts_each_step_from_the_handoff(
        tmp_path, monkeypatch, fake_cli):
    sent, folder = run_two(tmp_path, monkeypatch, fake_cli,
                           block(["calc.py:1-2 - add subtracts"]),
                           head="brief: false\n")
    first, second = sent
    assert not briefed(first) and not briefed(second)
    assert "kept-quote-marker" not in second
    assert "calc.py: add subtracts, the cause" in second
    assert "{BRIEF}" not in second


def test_a_step_says_whether_it_gets_the_brief_over_the_flow(
        tmp_path, monkeypatch, fake_cli):
    sent, _ = run_two(tmp_path, monkeypatch, fake_cli,
                      block(["calc.py:1-2 - add subtracts"]),
                      steps=("reader", "worker\nbrief: false"))
    assert briefed(sent[0]) and not briefed(sent[1])
    assert "calc.py: add subtracts, the cause" in sent[1]


def test_a_step_may_take_the_brief_in_a_flow_that_has_it_off(
        tmp_path, monkeypatch, fake_cli):
    sent, _ = run_two(tmp_path, monkeypatch, fake_cli,
                      block(["calc.py:1-2 - add subtracts"]),
                      steps=("reader", "worker\nbrief: true"),
                      head="brief: false\n")
    assert not briefed(sent[0])
    assert "return a - b  # kept-quote-marker" in sent[1]


def test_the_brief_key_takes_true_or_false_and_nothing_else():
    from agentweft.flow import spec

    assert spec.check({"name": "x", "brief": False,
                       "steps": [{"role": "worker", "brief": True}]}) == []
    assert spec.check({"name": "x", "brief": "maybe",
                       "steps": [{"role": "worker"}]}) == \
        ["brief should be bool"]
    assert spec.check({"name": "x", "steps": [
        {"role": "worker", "brief": "off"}]}) == \
        ["step 0: brief should be true or false"]
