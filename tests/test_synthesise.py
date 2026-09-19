"""the judge, against the file that specifies it.

`agents/architect.md` has been the final judge since the workflow file came
over and nothing had ever read its table. these hold the table, the brief a
judge is handed and the shape of what comes back against that file rather than
against a copy of it typed out here.
"""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.orchestrate import synthesise, workflow
from agentweft.roles import resolver
from agentweft.runner import engine, prompts

NL = chr(10)

GOOD = NL.join([
    "VERDICT: redo",
    "",
    "## Rulings",
    "- the parser is in three files -> extract it -> the same logic now lives "
    "in 3+ places",
    "- the renamed helper -> drop it -> the change only serves elegance",
    "",
    "## Must fix",
    "1. pull the parser into agentweft/flow/reader.py",
    "",
    "## Deliberately not fixing",
    "- the helper's name. it is not what the feature asked for.",
    "",
])


def test_the_table_is_read_off_the_file_that_specifies_it():
    """six rulings, and the file's own words for them.

    a copy of them in python would be a second answer to the same conflict,
    which is the failure `project.py` avoids by borrowing `spec.TIERS`.
    """
    rules = synthesise.table()
    assert len(rules) == 6
    said = [str(r) for r in rules]
    assert "The same logic now lives in 3+ places -> extract it" in said
    assert "The change is required to make a test pass -> allowed, always" in said
    text = (workflow.root() / "agents" / synthesise.JUDGE).read_text(encoding="utf-8")
    for rule in rules:
        assert rule.situation in text
        assert rule.ruling in text


def test_a_checkout_without_the_agent_file_still_has_a_judge(tmp_path):
    """the table is the phase side's and the judge is not.

    it hands back nothing rather than raising, and the brief leaves the section
    out instead of sending a heading with no rulings under it.
    """
    assert synthesise.table(tmp_path / "gone.md") == []
    text = synthesise.brief([synthesise.Report("reviewer", "fine")], rules=[])
    assert "reviewer" in text
    assert "already decided" not in text


def test_every_report_arrives_under_the_name_of_who_wrote_it():
    """the whole difference between judging and averaging.

    "they are not asked to be balanced, so do not average them" only means
    something if the judge can tell whose report is whose, which is what a
    fan-in that concatenates throws away.
    """
    text = synthesise.brief([synthesise.Report("minimalist", "it is fine"),
                             synthesise.Report("refactor-advocate", "extract it")])
    assert "--- minimalist ---" in text
    assert "--- refactor-advocate ---" in text
    assert text.index("minimalist") < text.index("refactor-advocate")
    assert "do not average them" in text


def test_the_brief_carries_the_rulings_that_are_already_decided():
    text = synthesise.brief([synthesise.Report("a", "x")])
    for rule in synthesise.table():
        assert str(rule) in text


def test_a_judgement_reads_back_as_its_four_parts():
    v = synthesise.read(GOOD)
    assert v.word == "redo"
    assert v.verdict() == "redo"
    assert len(v.rulings) == 2
    assert v.rulings[0].decision == "extract it"
    assert v.must_fix == ["pull the parser into agentweft/flow/reader.py"]
    assert v.not_fixing == ["the helper's name. it is not what the feature asked for."]
    assert synthesise.faults(v) == []


def test_an_item_that_wraps_is_still_one_item():
    """the reason is the whole value of the last section, and a reason is
    longer than a line. a paragraph after the list is not part of it."""
    v = synthesise.read(NL.join([
        "VERDICT: ok", "", "## Rulings", "- a -> b -> extract it", "",
        "## Deliberately not fixing",
        "- sharing the parser. two places is not three,",
        "  and the two markers are different.",
        "",
        "that is everything they raised.", ""]))
    assert v.not_fixing == ["sharing the parser. two places is not three, "
                            "and the two markers are different."]


def test_the_agent_files_own_spelling_is_read_too():
    """the file answers APPROVED and the router reads ok, and this has to take
    both: a judgement written to the file's shape puts the word in a section."""
    v = synthesise.read(NL.join(["## Verdict", "APPROVED", "",
                                 "## Rulings", "- a -> b -> extract it", "",
                                 "## Deliberately not fixing", "- nothing", ""]))
    assert v.word == "APPROVED"
    assert v.verdict() == "ok"
    assert synthesise.faults(v) == []


def test_a_ruling_says_which_row_of_the_table_it_used():
    rules = synthesise.table()
    ruling = synthesise.Ruling("x", "extract it", "lives in 3+ places")
    assert ruling.rule(rules).ruling == "extract it"
    assert synthesise.Ruling("x", "y", "because i said so").rule(rules) is None
    assert synthesise.Ruling("x", "y", "").rule(rules) is None


def a_judgement(ruling):
    return NL.join(["VERDICT: ok", "", "## Rulings", "- " + ruling, "",
                    "## Deliberately not fixing", "- nothing"])


def test_a_ruling_with_nothing_behind_it_is_a_fault():
    """the file's line is [conflict] -> [decision] -> [which rule above], and
    the two ways to fall short of it are different complaints."""
    v = synthesise.read(a_judgement("they disagreed"))
    assert synthesise.faults(v) == ["no decision in: they disagreed"]
    v = synthesise.read(a_judgement("they disagreed -> i picked one"))
    assert synthesise.faults(v) == ["no rule in the table behind: they disagreed"]
    v = synthesise.read(a_judgement("they disagreed -> i picked one -> vibes"))
    assert synthesise.faults(v) == ["no rule in the table behind: they disagreed"]


CITED = a_judgement("they disagreed -> i picked one -> vibes")


def test_a_table_that_did_not_parse_is_its_own_complaint(tmp_path):
    """the ruling check goes quiet when there are no rules, so an empty table
    has to be able to say why it is empty. the header is the only way in, and
    renaming a column is enough to lose the whole thing."""
    real = (workflow.root() / "agents"
            / synthesise.JUDGE).read_text(encoding="utf-8")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / synthesise.JUDGE).write_text(
        real.replace(synthesise.HEAD, "| Situation | Decision |"),
        encoding="utf-8")
    was = workflow.ROOT[0]
    workflow.ROOT[0] = str(tmp_path)
    try:
        assert synthesise.table() == []
        bad = synthesise.faults(synthesise.read(CITED))
        assert [f for f in bad if f.startswith("the conflict table")]
    finally:
        workflow.ROOT[0] = was


def test_a_missing_agent_file_is_still_not_a_complaint(tmp_path):
    """the other empty table is a stance and stays one. a checkout without
    `orchestrate/` has a judge; what it has not got is the six rulings, and
    holding a judgement against rules nobody shipped would be the complaint
    landing on whoever is least able to answer it."""
    was = workflow.ROOT[0]
    workflow.ROOT[0] = str(tmp_path)
    try:
        assert synthesise.table() == []
        assert synthesise.faults(synthesise.read(CITED)) == []
    finally:
        workflow.ROOT[0] = was


def test_both_have_a_point_is_not_a_ruling():
    """the file names that phrase itself, so this does too."""
    v = synthesise.read(GOOD.replace("drop it", "both have a point"))
    assert '"both have a point" is not a ruling' in synthesise.faults(v)


def test_the_last_section_is_not_optional():
    v = synthesise.read(GOOD.split("## Deliberately not fixing")[0])
    assert [f for f in synthesise.faults(v) if f.startswith("no deliberately")]


def test_sending_work_back_without_saying_what_to_fix():
    v = synthesise.read(GOOD.replace("1. pull the parser into "
                                     "agentweft/flow/reader.py", ""))
    assert "sent back and named nothing to fix" in synthesise.faults(v)


def test_a_judgement_that_never_answered_is_the_first_complaint():
    v = synthesise.read("i read all three and they are all reasonable")
    assert v.verdict() == ""
    assert synthesise.faults(v)[0].startswith("no verdict")


def test_what_the_file_asks_for_and_nothing_here_checks():
    """a requirement quietly skipped reads exactly like one that passed."""
    assert len(synthesise.UNCHECKED) == 3
    for what, why in synthesise.UNCHECKED:
        assert what and why


def test_the_library_says_what_a_judge_is_and_it_is_not_what_merge_is():
    """merge stitches and adds nothing; deciding between two reports is adding
    something neither of them said. the library now has words for both."""
    judge = resolver.role_prompt("judge.md")
    merge = resolver.role_prompt("merge.md")
    assert "VERDICT: redo" in judge
    assert "VERDICT" not in merge
    assert "do not add anything" in merge
    assert "do not average them" in judge
    assert "judge" in resolver.library_roles()
    assert resolver.EXTRA["judge"] == ["reviewer-only"]


def test_a_step_can_name_the_reports_it_judges():
    s = spec.load({"name": "x", "steps": [
        {"role": "worker"}, {"role": "reviewer"},
        {"role": "judge", "reports": ["worker", "reviewer"]}]})
    assert s.steps[-1]["reports"] == ["worker", "reviewer"]


def test_a_step_cannot_judge_a_report_nobody_wrote():
    """a typo here would read as a judge with one report fewer, which is a
    judge with nothing to decide rather than a flow that refused to load."""
    with pytest.raises(ValueError) as e:
        spec.load({"name": "x", "steps": [
            {"role": "worker"},
            {"role": "judge", "reports": ["workr"]}]})
    assert "reports workr, which is not a role or a step before it" in str(e.value)
    assert "there is: worker" in str(e.value)


def test_a_step_cannot_judge_something_that_has_not_run_yet():
    with pytest.raises(ValueError) as e:
        spec.load({"name": "x", "steps": [
            {"role": "judge", "reports": ["reviewer"]},
            {"role": "reviewer"}]})
    assert "there is: nothing" in str(e.value)


def test_reports_is_a_list():
    with pytest.raises(ValueError) as e:
        spec.load({"name": "x", "steps": [{"role": "worker"},
                                          {"role": "judge", "reports": "worker"}]})
    assert "reports should be a list" in str(e.value)


FLAT = ("name: judged" + NL
        + "steps:" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL
        + "  - role: reviewer" + NL
        + "    prompt: reviewer.md" + NL
        + "  - role: judge" + NL
        + "    prompt: judge.md" + NL
        + "    reports: [worker, reviewer]" + NL)
FANNED = ("name: judged" + NL
          + "steps:" + NL
          + "  - role: planner" + NL
          + "    prompt: planner.md" + NL
          + "  - role: worker" + NL
          + "    prompt: worker.md" + NL
          + "    fanout: true" + NL
          + "    workers: 2" + NL
          + "  - role: judge" + NL
          + "    prompt: judge.md" + NL
          + "    reports: [planner, worker]" + NL)
TAIL = ("journal: false" + NL
        + "provider:" + NL
        + "  provider: fake" + NL)
RULED = NL.join(["VERDICT: ok", "", "## Rulings",
                 "- both read it -> keep the worker's line -> "
                 "the change serves the feature", "",
                 "## Deliberately not fixing", "- nothing else was raised", ""])


def a_flow(tmp_path, body):
    d = tmp_path / "flows" / "judged"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(body + TAIL, encoding="utf-8")
    (d / "instructions.md").write_text("decide it." + NL, encoding="utf-8")
    for role in ("planner", "worker", "reviewer"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    return tmp_path / "flows"


def go(tmp_path, monkeypatch, body, answers):
    """run main() over a throwaway flow, and say what each step was sent."""
    root = a_flow(tmp_path, body)
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent[step] = prompt
        return answers.get(step, "nothing to report"), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv",
                        ["run.py", "judged", "--force", "--flows", str(root)])
    monkeypatch.chdir(tmp_path)
    engine.main()
    return sent


def test_a_step_that_names_its_reports_is_handed_all_of_them(tmp_path, monkeypatch):
    """the step runs, and what reaches it is both reports and the table.

    this is the whole of what is new: a step has always been handed whatever
    ran immediately before it, and the judge needs the ones that disagree.
    """
    sent = go(tmp_path, monkeypatch, FLAT,
              {"worker.md": "a.py is fine", "reviewer.md": "a.py is not fine",
               "judge.md": RULED})
    judge = sent["judge.md"]
    assert "--- worker ---" in judge
    assert "--- reviewer ---" in judge
    assert "a.py is fine" in judge
    assert "a.py is not fine" in judge
    for rule in synthesise.table():
        assert str(rule) in judge


def test_the_report_it_judges_does_not_arrive_twice(tmp_path, monkeypatch):
    """the step before it is one of the reports, and it used to be appended
    again unlabelled. the same text twice, once with a name on it and once
    without, is the judge being told to weigh one of them heavier."""
    sent = go(tmp_path, monkeypatch, FLAT,
              {"worker.md": "a.py is fine", "reviewer.md": "a.py is not fine",
               "judge.md": RULED})
    assert "here is what reviewer produced" not in sent["judge.md"]
    assert sent["judge.md"].count("a.py is not fine") == 1
    # a step that names nothing is chained the way it always was
    assert "here is what worker produced" in sent["reviewer.md"]


def test_the_judge_gets_the_library_words_and_answers_in_them(tmp_path,
                                                              monkeypatch):
    """the flow ships no judge.md, so every word it gets is the library's."""
    sent = go(tmp_path, monkeypatch, FLAT,
              {"worker.md": "a.py is fine", "reviewer.md": "a.py is not fine",
               "judge.md": RULED})
    assert "VERDICT: redo" in sent["judge.md"]
    assert "you are allowed to say the work is wrong" in sent["judge.md"]
    saved = [p for p in (tmp_path / "runs").iterdir()
             if p.is_file() and p.name.startswith("judged")]
    verdict = synthesise.read(saved[0].read_text(encoding="utf-8"))
    assert verdict.verdict() == "ok"
    assert synthesise.faults(verdict) == []


def test_a_fanned_out_step_is_reported_as_the_whole_of_what_it_produced(
        tmp_path, monkeypatch):
    """every task goes through the same per-step call, so what a judge is
    handed has to be the joined output and not whichever one finished last."""
    sent = go(tmp_path, monkeypatch, FANNED,
              {"planner.md": "a.py | look at a" + NL + "b.py | look at b",
               "worker.md": "one task done", "judge.md": RULED})
    judge = sent["judge.md"]
    assert "--- planner ---" in judge
    assert "--- worker ---" in judge
    assert judge.count("one task done") == 2


def test_a_report_that_has_not_run_is_left_out_rather_than_sent_empty():
    """a resumed run starts in the middle, and a real name over an empty
    report is worse than one report fewer."""
    fm = spec.load({"name": "x", "steps": [
        {"role": "worker"}, {"role": "reviewer"},
        {"role": "judge", "reports": ["worker", "reviewer"]}]})
    # the name is only what `fanout_step` opens on the way in; the steps being
    # asked about are the spec's, not that file's
    run = engine.Run("code-review", fm, {"worker": "", "reviewer": "", "judge": ""},
                     provider={"provider": "fake"})
    # what a step produced is filed under the step, so two of one role are two
    # reports; `reports: [reviewer]` is still the name a flow writes
    run.produced["reviewer.md"] = "only this one ran"
    assert [r.source for r in run.reports_for("judge.md")] == ["reviewer"]
    # a step that gave up produced the empty string, which is a name over
    # nothing rather than a report
    run.produced["worker.md"] = ""
    assert [r.source for r in run.reports_for("judge.md")] == ["reviewer"]
    assert run.reports_for("worker.md") == []
    assert run.reports_for("nobody.md") == []
