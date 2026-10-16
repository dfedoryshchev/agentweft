"""the top of handoff.md is what a person reads by default: the outcome and
one sentence, the suite, the one decision with a recommendation and its size,
then why, what was not done and the product gaps, each doubt once. the full
record follows below it."""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.runner import front, handoff, stops, summary, verbs

NO_GIT = {"git": False}


def a_pass(role, said, outcome="ok"):
    return summary.a_pass(role + ".md", role, 1.0, handoff.parse(said), [],
                          False, outcome, said)


def block(**sections):
    out = ["HANDOFF"]
    for name, items in sections.items():
        out.append(name.upper().replace("_", " ") + ":")
        out.extend("- " + i for i in items)
    return "\n".join(out + ["END HANDOFF", ""])


def build(passes, stopped=None, run_id="f-1"):
    return summary.build(run_id, "f", "round the amounts", passes, NO_GIT, [],
                         "1 call", stopped=stopped)


def default_view(lines):
    assert "## full record" in lines, "\n".join(lines)
    return lines[:lines.index("## full record")]


def outside_needs_you(lines):
    note = "\n".join(lines)
    if "## needs you\n" not in note:
        return note
    before, after = note.split("## needs you\n", 1)
    return before + "\n## " + after.split("\n## ", 1)[1]


QUESTION = "Should a blank amount count as zero (TASK.md:12)?"
QUESTION_WORDS = "should a blank amount count as zero"


def test_seven_copies_of_one_question_print_once_with_a_recommendation():
    # QUESTION lines, not NEEDS: a finished run answered every NEEDS on the
    # way, so only a question that never stopped the run is still open
    asked = ("rounded half up\n\nHANDOFF\nDID:\n- money.py: rounds half up\n"
             "QUESTION: " + QUESTION + "\n"
             "RECOMMEND: treat blank as zero, as the importer already does\n"
             "SIZE: one line in money.py\nEND HANDOFF\n")
    passes = [
        a_pass("worker", asked),
        a_pass("tester", "HANDOFF\nQUESTION: should a blank amount count as"
               " zero? TASK.md:12\nEND HANDOFF\n"),
        a_pass("reviewer", block(doubts=[
            "should a  BLANK amount count as zero? TASK.md:12",
            "TASK.md:12 does not say what a blank amount is?"])),
        a_pass("architect", block(doubts=[
            "Should a blank amount count as zero (TASK.md:12)?"])),
        a_pass("qa", block(doubts=[
            "should a blank amount count as zero (TASK.md:12)?"])),
    ]
    lines = build(passes)
    top = "\n".join(default_view(lines))
    assert top.lower().count("blank amount") == 1, top
    decision = top.split("## the one decision\n")[1].split("\n## ")[0]
    assert "raised by worker, tester, reviewer, architect, qa" in decision
    assert "recommendation: treat blank as zero, as the importer already" \
        " does (size: one line in money.py)" in decision
    record = outside_needs_you(lines).split("\n")
    same = [l for l in record if QUESTION_WORDS in front.norm(l)]
    assert len(same) == 1, same


def test_a_stop_opens_with_its_outcome_and_never_a_fixed_lead():
    said = block(did=["fixed the rounding in money.py",
                      "money.py: rounds half up"])
    lines = build([a_pass("worker", said)],
                  stopped={"cause": stops.CONFLICT, "at": "worker.md",
                           "why": "TASK.md:3 says amounts round down"})
    assert lines[0].startswith("# f f-1: stopped: spec conflict at worker.md")
    assert "fixed" not in "\n".join(lines[:4])
    why = "\n".join(default_view(lines)).split("## why\n")[1].split("\n## ")[0]
    assert "not taken as done" in why


def test_a_finished_run_leads_with_what_it_did_and_says_nothing_waits():
    lines = build([a_pass("worker", block(did=["money.py: rounds half up"]))])
    assert lines[0] == "# f f-1: done - money.py: rounds half up"
    top = default_view(lines)
    assert any(l.startswith("suite: ") for l in top[:6])
    decision = "\n".join(top).split("## the one decision\n")[1]
    assert decision.startswith("- none: nothing waits on you")


def test_each_doubt_prints_once_by_its_text_and_by_the_line_it_cites():
    passes = [
        a_pass("worker", block(doubts=["the CSV header may carry a BOM",
                                       "notes.md:4 still names the old flag"])),
        a_pass("tester", block(doubts=["The csv header may  carry a bom."])),
        a_pass("reviewer", block(doubts=[
            "the old flag is still named at notes.md:4, worth a sweep"])),
    ]
    lines = build(passes)
    top = "\n".join(default_view(lines)).lower()
    assert top.count("bom") == 1
    assert top.count("notes.md:4") == 1
    assert "(worker, tester)" in top
    doubts = "\n".join(lines).split("## doubts\n")[1].split("\n## ")[0]
    assert doubts.lower().count("bom") == 1


def test_the_default_view_of_a_long_run_stays_in_budget_and_links_the_rest():
    long = "x" * 140
    passes = [a_pass("step" + str(n), block(
        did=["did " + str(n) + " " + long, "file" + str(n) + ".py: " + long],
        doubts=["doubt " + str(n) + " " + long],
        not_verified=["unchecked " + str(n) + " " + long],
        assumed=["chose " + str(n) + " | why: " + long + " | if wrong: x"]))
        for n in range(30)]
    lines = build(passes, run_id="f-9")
    top = default_view(lines)
    assert len("\n".join(top)) / 4 <= 900
    assert "more in the full record below" in "\n".join(top)
    rest = "\n".join(lines[len(top):])
    assert rest.startswith("## full record\n")
    assert "runs/f-9/" in rest.split("\n## ")[0]
    for n in range(30):
        assert "doubt " + str(n) + " " in rest


def test_the_console_prints_the_default_view_and_not_the_record():
    lines = build([a_pass("worker", block(did=["money.py: rounds half up"]))])
    shown = summary.top(lines)
    assert "## the one decision" in shown
    assert "## changed" not in shown


def test_a_question_carries_its_recommendation_and_size_on_labelled_lines():
    v = verbs.parse("NEEDS: blank as zero?\nRECOMMEND: yes\nSIZE: one line\n")
    assert (getattr(v, "recommend", None), getattr(v, "size", None)) == \
        ("yes", "one line")
    lines = build([a_pass("worker", "NEEDS: blank as zero (TASK.md:2)?\n"
                          "RECOMMEND: yes, as the importer does\n"
                          "SIZE: one line in money.py\n")],
                  stopped={"cause": stops.PARKED, "at": "worker.md",
                           "why": "worker.md asks a question"})
    assert "  recommendation: yes, as the importer does (size: one line in" \
        " money.py)" in default_view(lines)


ASKED_IN_THE_BLOCK = (
    "rounded half up\n\nHANDOFF\nDID:\n- money.py: rounds half up\n"
    "QUESTION: should a blank amount count as zero (TASK.md:12)?\n"
    "RECOMMEND: treat blank as zero, as the importer does\n"
    "SIZE: one line in money.py\n"
    "QUESTION: should negative amounts round away from zero?\n"
    "RECOMMEND: yes\nSIZE: one line\nEND HANDOFF\n")


def test_a_question_in_the_block_is_read_with_its_recommendation_and_size():
    got = handoff.parse(ASKED_IN_THE_BLOCK)
    assert [(q["question"], q["recommend"], q["size"])
            for q in got.get("questions", [])] == [
        ("should a blank amount count as zero (TASK.md:12)?",
         "treat blank as zero, as the importer does", "one line in money.py"),
        ("should negative amounts round away from zero?", "yes", "one line")]
    assert got["other"] == {}


def test_a_step_that_asks_in_its_block_finishes_and_the_decision_shows_it(
        tmp_path, monkeypatch, fake_cli):
    from agentweft.runner import engine
    from test_stops import a_flow, answer, the_folder

    a_flow(tmp_path, monkeypatch, "f", ["worker"])
    fake_cli(answer(ASKED_IN_THE_BLOCK))
    assert engine.main() == 0
    note = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    lines = note.split("\n")
    assert ": done - money.py: rounds half up" in lines[0]
    top = "\n".join(default_view(lines))
    decision = top.split("## the one decision\n")[1].split("\n## ")[0]
    assert decision.count("blank amount") == 1
    assert "recommendation: treat blank as zero, as the importer does" \
        " (size: one line in money.py)" in decision
    assert "round away from zero" in decision
    assert "## needs you" not in note


def test_no_shipped_prompt_teaches_needs_as_a_way_to_file_a_doubt():
    text = (Path("agentweft") / "fragments" / "handoff.md").read_text(
        encoding="utf-8")
    assert "NEEDS:" not in text
    assert "QUESTION:" in text and "RECOMMEND:" in text and "SIZE:" in text


def test_no_shipped_prompt_teaches_a_pipe_separated_question():
    shipped = list((Path("agentweft") / "fragments").glob("*.md"))
    shipped += list(Path("flows").rglob("*.md"))
    assert shipped
    for path in shipped:
        text = path.read_text(encoding="utf-8").lower()
        assert "| recommend:" not in text, path
        assert "| size:" not in text, path
