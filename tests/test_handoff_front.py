"""the top of handoff.md is what a person reads by default: the outcome and
one sentence, the suite, the one decision with a recommendation and its size,
then why, what was not done and the product gaps, each doubt once. the full
record follows below it."""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.runner import front, handoff, stops, summary, verbs
from agentweft.runner.front import MORE

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


def test_a_done_run_whose_block_asks_none_says_nothing_waits_on_a_person():
    said = ("HANDOFF\nDID:\n- money.py: rounds half up\nQUESTION: none\n"
            "RECOMMEND: none\nSIZE: none\nEND HANDOFF\n")
    lines = build([a_pass("worker", said)])
    assert handoff.parse(said)["questions"] == []
    assert decision_of(lines).strip() == "- none: nothing waits on you."
    assert "raised by" not in "\n".join(default_view(lines))


def test_a_none_question_does_not_lend_its_answer_to_the_one_before_it():
    said = ("HANDOFF\nDID:\n- money.py: rounds half up\n"
            "QUESTION: " + QUESTION + "\nRECOMMEND: treat blank as zero\n"
            "SIZE: one line\nQUESTION: none\nRECOMMEND: none\nSIZE: none\n"
            "END HANDOFF\n")
    assert [(q["question"], q["recommend"], q["size"])
            for q in handoff.parse(said)["questions"]] == [
        (QUESTION, "treat blank as zero", "one line")]
    decision = decision_of(build([a_pass("worker", said)]))
    assert decision.strip().split("\n") == [
        "- " + QUESTION,
        "  raised by worker; cites TASK.md:12",
        "  recommendation: treat blank as zero (size: one line)"]


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


def decision_of(lines):
    top = "\n".join(default_view(lines))
    return top.split("## the one decision\n")[1].split("\n## ")[0]


def test_on_a_stop_the_one_decision_is_the_question_the_run_waits_on():
    early = block(did=["calc.py: read it"],
                  doubts=["should the log line be shorter?"])
    asking = ("NEEDS: TASK.md:7 does not say whether a blank amount is zero\n"
              "RECOMMEND: treat it as zero\nSIZE: one line\n")
    lines = build([a_pass("worker", early), a_pass("patcher", asking, "asked")],
                  stopped={"cause": stops.PARKED, "at": "patcher.md",
                           "why": "patcher.md needs a ruling"})
    decision = decision_of(lines)
    assert "blank amount" in decision.split("\n")[0], decision
    assert "log line" in decision.split("also open:")[1], decision
    gaps = "\n".join(default_view(lines)).split("## product gaps\n")[1]
    assert "TASK.md:7 - the one decision turns on it" in gaps


def test_a_finished_run_keeps_its_questions_in_the_order_they_were_asked():
    lines = build([
        a_pass("worker", block(doubts=["should the log line be shorter?"])),
        a_pass("reviewer", block(doubts=["should a blank amount be zero?"]))])
    assert "log line" in decision_of(lines).split("\n")[0]


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


def test_no_shipped_prompt_teaches_a_pipe_separated_assumption():
    from agentweft.roles import resolver

    composed = resolver.fragment("handoff")
    assert "ASSUMED:" in composed
    taught = composed.split("ASSUMED:", 1)[1].split("DOUBTS:", 1)[0]
    assert "|" not in taught
    assert "\n      why: " in taught and "\n      if wrong: " in taught
    shipped = list((Path("agentweft") / "fragments").glob("*.md"))
    shipped += list(Path("flows").rglob("*.md"))
    for path in shipped:
        text = path.read_text(encoding="utf-8").lower()
        assert "| why:" not in text, path
        assert "| if wrong:" not in text, path


def stopped_decision(tmp_path, monkeypatch, fake_cli, said, steps=None,
                     tail=None):
    """-> (exit code, the one decision) of a run whose worker answers
    `said`, and the question.md the stop wrote, "" for none."""
    from agentweft.runner import engine
    from test_stops import CLAUDE, a_flow, answer, the_folder

    (tmp_path / "TASK.md").write_text("amounts are strings\n",
                                      encoding="utf-8")
    a_flow(tmp_path, monkeypatch, "f", steps or ["worker", "reviewer"],
           tail=tail or CLAUDE)
    fake_cli(answer(said))
    code = engine.main()
    folder = the_folder()
    asked = folder / "question.md"
    note = (folder / "handoff.md").read_text(encoding="utf-8").split("\n")
    return code, decision_of(note), (asked.read_text(encoding="utf-8")
                                     if asked.exists() else "")


def test_a_park_on_a_verdict_shows_the_question_it_waits_on(
        tmp_path, monkeypatch, fake_cli):
    code, decision, asked = stopped_decision(
        tmp_path, monkeypatch, fake_cli,
        "VERDICT: park\nis a blank amount zero or an error?\n")
    assert code == 2 and "blank amount" in asked
    assert decision.startswith("- is a blank amount zero or an error?\n"), \
        decision
    assert "raised by worker\n" in decision
    assert "no step asked one" not in decision


def test_an_uncited_refusal_shows_the_question_it_became(
        tmp_path, monkeypatch, fake_cli):
    code, decision, asked = stopped_decision(
        tmp_path, monkeypatch, fake_cli,
        "REFUSED: rounding money down is unsafe\n")
    assert code == 2 and "rounding money" in asked
    assert decision.startswith("- rounding money down is unsafe (refused"
                               " with no line of the spec cited)"), decision
    assert "no step asked one" not in decision


BANNER = ("one\ntwo\n\nHANDOFF\nDID:\n- banner.py: draws it\n"
          "QUESTION: should the banner be blue?\nEND HANDOFF\n")


def test_a_gate_stop_leads_its_decision_with_the_stop_not_a_question(
        tmp_path, monkeypatch, fake_cli):
    code, decision, _ = stopped_decision(
        tmp_path, monkeypatch, fake_cli, BANNER,
        steps=["worker\ngates:\n  - gate: length\n    max_lines: 1",
               "reviewer"])
    assert code == 2
    first = decision.split("\n")[0]
    assert first.startswith("- stopped: gate failed at worker.md - length:"), \
        decision
    assert "banner" not in first
    assert "  also open:\n  - should the banner be blue?" in decision


def test_a_budget_stop_leads_its_decision_with_the_cap(
        tmp_path, monkeypatch, fake_cli):
    from test_stops import CLAUDE
    code, decision, _ = stopped_decision(
        tmp_path, monkeypatch, fake_cli, BANNER, tail=CLAUDE + "max_calls: 1\n")
    assert code == 2
    first = decision.split("\n")[0]
    assert first.startswith("- needs you: budget at reviewer.md"), decision
    assert "should the banner be blue?" in decision
    assert "banner" not in first


def test_a_needs_does_not_take_the_recommendation_of_a_block_question(
        tmp_path, monkeypatch, fake_cli):
    said = ("NEEDS: is a blank amount zero?\n\nHANDOFF\nDID:\n- read it\n"
            "QUESTION: should the banner be blue?\nRECOMMEND: yes, blue\n"
            "SIZE: one line\nEND HANDOFF\n")
    assert (verbs.parse(said).recommend, verbs.parse(said).size) == \
        (None, None)
    _, decision, _ = stopped_decision(tmp_path, monkeypatch, fake_cli, said)
    lines = decision.split("\n")
    assert lines[:3] == [
        "- is a blank amount zero?", "  raised by worker",
        "  recommendation: none given by a step that raised it"], decision
    assert "should the banner be blue? (worker; recommendation: yes, blue" \
        " (size: one line))" in decision


def test_a_recommendation_under_a_needs_is_its_own():
    v = verbs.parse("QUESTION: should the banner be blue?\nNEEDS: is a"
                    " blank amount zero?\nRECOMMEND: zero\nSIZE: one line\n")
    assert (v.recommend, v.size) == ("zero", "one line")


def test_a_second_question_on_one_spec_line_is_kept_in_the_full_record():
    said = ("HANDOFF\nDID:\n- money.py: rounds\n"
            "QUESTION: should a blank amount at TASK.md:4 be zero?\n"
            "QUESTION: may TASK.md:4 drop the currency sign?\nEND HANDOFF\n")
    lines = build([a_pass("worker", said)])
    assert "raised by worker; cites TASK.md:4" in decision_of(lines)
    record = lines[lines.index("## full record"):]
    assert "- worker: may TASK.md:4 drop the currency sign? (recommendation:" \
        " none given by a step that raised it)" in record, "\n".join(record)


def test_the_same_words_about_two_spec_lines_are_two_doubts():
    lines = build([a_pass("worker", block(doubts=[
        "TASK.md:3 does not say what an empty row does",
        "TASK.md:9 does not say what an empty row does"]))])
    record = "\n".join(lines[lines.index("## doubts"):])
    assert "TASK.md:3 does not say" in record
    assert "TASK.md:9 does not say" in record
    top = "\n".join(default_view(lines))
    assert "TASK.md:9" in top


def test_a_question_past_the_cut_is_in_the_full_record():
    asked = ["should option " + str(n) + " be on by default?"
             for n in range(10)]
    lines = build([a_pass("worker", block(did=["opts.py: reads them"],
                                          doubts=asked))])
    top = default_view(lines)
    assert any(MORE in l for l in top), "\n".join(top)
    note = "\n".join(lines)
    for q in asked:
        assert note.count(q) == 1, q


def test_a_doubt_left_after_a_send_back_says_how_many_times():
    bom = block(did=["csv.py: reads it"],
                doubts=["the CSV header may carry a BOM"])
    lines = build([a_pass("worker", bom, outcome="redo"),
                   a_pass("worker", bom)])
    record = lines[lines.index("## doubts"):]
    assert "- worker, 2 times: the CSV header may carry a BOM" in record, \
        "\n".join(record)
    top = "\n".join(default_view(lines))
    assert "the CSV header may carry a BOM (worker, 2 times)" in top, top


def test_a_long_task_line_and_stop_reason_still_fit_the_budget():
    lines = summary.build("f-1", "f", "round " * 1000, [a_pass("worker", block(
        did=["money.py: rounds half up"]))], NO_GIT, [], "1 call",
        stopped={"cause": stops.GATE, "why": "pytest said " + "x" * 3000,
                 "at": "worker.md"})
    top = default_view(lines)
    assert front.tokens(top) <= front.BUDGET, front.tokens(top)
    assert lines[0].startswith("# f f-1: stopped: gate failed at worker.md")
    assert "x" * 3000 in "\n".join(lines[len(top):])


def test_a_conflict_stop_lists_the_quote_check_it_ran(
        tmp_path, monkeypatch, fake_cli):
    from agentweft.runner import engine
    from test_stops import a_flow, answer, the_folder

    (tmp_path / "TASK.md").write_text("amounts are strings\n",
                                      encoding="utf-8")
    a_flow(tmp_path, monkeypatch, "f", ["worker", "reviewer"])
    fake_cli(answer('CONFLICT: TASK.md:1 "amounts are strings"\n'
                    "REQUEST: make them numbers\n"))
    assert engine.main() == 2
    note = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    assert "no gates ran" not in note
    lines = note.split("\n")
    [suite] = [l for l in lines if l.startswith("suite: ")]
    assert suite.startswith("suite: 1 check passed (the quote at TASK.md:1"
                            " is there as the run found it)"), suite
    checks = lines[lines.index("## tests and checks"):]
    assert "- worker.md: PASS quote check - the quote at TASK.md:1 is there" \
        " as the run found it" in checks, "\n".join(checks)


def spec_run(added, removed, spec_files=None):
    changes = {"git": True, "start": "abc", "commits": [], "status": [],
               "log": [], "ranges": {}, "tests_changed": [],
               "files": [("TASK.md", added, removed, "uncommitted")],
               "spec_changed": [("TASK.md", added, removed)]}
    return summary.build("f-1", "f", "add a rule", [a_pass("worker", block(
        did=["TASK.md: adds a rule"]))], changes, [], "1 call",
        spec_files=spec_files)


def test_a_spec_addition_the_flow_allows_is_not_an_unruled_change():
    lines = spec_run(2, 0, spec_files="additions")
    note = "\n".join(lines)
    assert "UNRULED" not in note
    assert "rule on" not in decision_of(lines)
    assert "- spec TASK.md +2 -0, lines added only, which spec_files:" \
        " additions allows, no ruling needed" in lines


def test_a_rewritten_spec_line_is_still_unruled_under_additions():
    lines = spec_run(1, 1, spec_files="additions")
    assert any("TASK.md +1 -1 <- UNRULED" in l for l in lines)
    assert "rule on spec TASK.md +1 -1" in decision_of(lines)


def test_a_spec_addition_without_the_additions_rule_is_still_unruled():
    lines = spec_run(2, 0)
    assert any("TASK.md +2 -0 <- UNRULED" in l for l in lines)
    assert "rule on spec TASK.md +2 -0" in decision_of(lines)
