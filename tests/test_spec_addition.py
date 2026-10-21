"""a request that adds an option the spec does not mention extends the spec;
only one that changes what a spec line requires, for the inputs and options
that line already covers, is a conflict.

the spec says fields are separated by commas. `--delimiter ;` that uses `;`
only when it is given leaves that line true and adds to it; making the comma a
semicolon contradicts it. a line that holds in every case, `an amount is never
0`, already covers every option, so `--allow-zero` contradicts it.

the runs here script the planner as a literal reader: it applies only the
rules the prompt it is sent states, in the prompt's own words, and answers in
the format that prompt teaches. no model is asked, so what a run does follows
from what the prompt says and nothing else.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.roles import resolver
from agentweft.runner import engine, gating, prompts, stops

from test_spec_conflict import a_place, end, folders, go, plain, unchanged

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"

SPEC = "# roster" + NL + NL + "- Fields are separated by commas." + NL
FIELDS = "def fields(line):" + NL + "    return line.split(',')" + NL
WITH_OPTION = ("def fields(line, delimiter=','):" + NL
               + "    return line.split(delimiter)" + NL)
BASELINE = ("from roster import fields" + NL + NL + NL
            + "def test_commas():" + NL
            + "    assert fields('a,b') == ['a', 'b']" + NL)
OPTION_TEST = ("def test_delimiter():" + NL
               + "    from roster import fields" + NL + NL
               + "    assert fields('a;b', delimiter=';') == ['a', 'b']" + NL)

ADDS = ("add --delimiter C to every command: the roster uses C instead of the"
        " comma to separate fields")
REWRITES = "the roster separates fields with a semicolon, not a comma"

PLAN = NL.join([
    "- behaviour: fields('a;b', delimiter=';') is ['a', 'b']",
    "  file: roster.py",
    "  spec: adds to TASK.md:3",
    "- behaviour: fields('a,b') with no delimiter is still ['a', 'b']",
    "  file: roster.py",
    "  spec: allows TASK.md:3", ""])
TESTER = ("FAILS: TypeError: fields() got an unexpected keyword argument"
          " 'delimiter'" + NL + "TEST: tests/test_delimiter.py" + NL)
BUILT = "- roster.py: fields takes a delimiter, the comma by default" + NL
# the words a rule is stated in, as the literal planner looks for them
ADDITION = "an addition is not a conflict"
EVERY_CASE = "already covers every option"
ABSOLUTE = ("never", "always", "only", "must")

PAY_SPEC = "# pay" + NL + NL + "- An amount is never 0." + NL
PAY = ("def pay(n):" + NL + "    if n == 0:" + NL
       + "        raise ValueError('an amount is never 0')" + NL
       + "    return n" + NL)
PAY_ZERO = ("def pay(n, allow_zero=False):" + NL
            + "    if n == 0 and not allow_zero:" + NL
            + "        raise ValueError('an amount is never 0')" + NL
            + "    return n" + NL)
PAY_BASELINE = ("import pytest" + NL + NL + "from pay import pay" + NL + NL
                + NL + "def test_zero_is_refused():" + NL
                + "    with pytest.raises(ValueError):" + NL
                + "        pay(0)" + NL)
ZERO_TEST = ("def test_allow_zero():" + NL + "    from pay import pay" + NL
             + NL + "    assert pay(0, allow_zero=True) == 0" + NL)
ALLOW_ZERO = "add --allow-zero so an amount of 0 is accepted when given"

CONTRADICTS = NL.join([
    "- behaviour: fields('a;b') is ['a', 'b']",
    "  file: roster.py",
    "  spec: contradicts TASK.md:3",
    'CONFLICT: TASK.md:3 "Fields are separated by commas."',
    "request: " + REWRITES, ""])


def composed(monkeypatch, step):
    """-> the prompt the build-feature step is sent, spaces flattened."""
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    fm = runner.config("build-feature")
    by_role = resolver.resolve(fm.raw, runner.flow_path("build-feature"))
    run = runner.Run("build-feature", fm, by_role, workdir=str(FLOWS))
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent[step] = " ".join(prompt.split())
        return "ok", False

    monkeypatch.setattr(engine, "call", fake_call)
    run.step(step)
    return sent[step]


def test_the_planner_is_told_an_added_option_is_not_a_conflict(monkeypatch):
    said = composed(monkeypatch, "planner.md")
    assert "spec: adds to TASK.md:<line>" in said
    assert "spec: contradicts TASK.md:<line>" in said
    assert "an addition is not a conflict" in said
    assert "only a behaviour marked `contradicts` may end the plan" in said
    assert "for the same inputs and options" in said
    assert EVERY_CASE in said and "--allow-zero" in said
    assert " | " not in said[said.find("- behaviour:"):][:200]


def test_every_step_is_told_what_a_conflict_is(monkeypatch):
    for step in ("planner.md", "tester.md", "worker.md"):
        said = composed(monkeypatch, step)
        assert "for the same inputs and options" in said, step
        assert "adds to the spec and is not a conflict" in said, step


def test_the_tester_tests_an_addition_like_any_other_behaviour(monkeypatch):
    said = composed(monkeypatch, "tester.md")
    assert "a behaviour marked `adds to` gets its test" in said


def literal(quote, request, option, behaviour, others=None):
    """-> a planner that reads the prompt it is sent and plans one behaviour
    against TASK.md:3, which says `quote`. `option` is whether the request
    adds an option rather than changing what the line says. it marks the
    behaviour `adds to` only when the prompt says an addition is not a
    conflict, and not when the prompt says a line that holds in every case
    covers every option and this line is one. the other steps answer from
    `others`."""
    def plan(said):
        absolute = any(w in quote.lower().split() for w in ABSOLUTE)
        adds = (option and ADDITION in said
                and not (EVERY_CASE in said and absolute))
        mark = "adds to" if adds else "contradicts"
        if "- behaviour:" in said:
            out = ["- behaviour: " + behaviour, "  file: the module",
                   "  spec: " + mark + " TASK.md:3"]
        else:
            out = ["- " + behaviour + " | the module | " + mark
                   + ": TASK.md:3"]
        if not adds:
            out = ['CONFLICT: TASK.md:3 "' + quote + '"',
                   "request: " + request] + out
        return NL.join(out) + NL

    def answer(step, n, prompt):
        if step == "planner.md":
            return plan(" ".join(prompt.split()))
        return dict({"reviewer.md": REVIEWED, "reviewer-runs.md": REVIEWED},
                    **(others or {}))[step]
    return answer


REVIEWED = "VERDICT: ok" + NL + NL + "- the change" + NL


def roster_place(tmp_path):
    return a_place(tmp_path / "project", {
        "TASK.md": SPEC, "roster.py": FIELDS, "conftest.py": "",
        "tests/test_roster.py": BASELINE})


def roster_edits(place):
    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_delimiter.py").write_text(
                OPTION_TEST, encoding="utf-8")
        if step == "worker.md":
            (place / "roster.py").write_text(WITH_OPTION, encoding="utf-8")
    return edits


def test_a_plan_that_adds_to_a_spec_line_is_built(tmp_path, monkeypatch):
    roster_place(tmp_path)
    place = tmp_path / "project"
    asked, sent, code = go(tmp_path, monkeypatch, "build-feature",
                           plain({"planner.md": [PLAN],
                                  "tester.md": [TESTER],
                                  "worker.md": [BUILT],
                                  "reviewer.md": ["VERDICT: ok" + NL + NL
                                                  + BUILT],
                                  "reviewer-runs.md": ["VERDICT: ok" + NL + NL
                                                       + BUILT]}),
                           roster_edits(place), "--task", ADDS)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md"]
    assert code == stops.EXIT_OK
    assert "spec: adds to TASK.md:3" in sent[1]
    assert "a behaviour marked `adds to` gets its test" in " ".join(
        sent[1].split())
    assert end(tmp_path).cause != "conflict"


def test_a_literal_planner_builds_an_added_delimiter(tmp_path, monkeypatch):
    roster_place(tmp_path)
    place = tmp_path / "project"
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        literal("Fields are separated by commas.", ADDS, True,
                                "fields('a;b', delimiter=';') is ['a', 'b']",
                                {"tester.md": TESTER, "worker.md": BUILT}),
                        roster_edits(place), "--task", ADDS)
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md"]
    assert code == stops.EXIT_OK


APPENDED = "- With --delimiter C, fields are separated by C instead." + NL
REWRITTEN = ("# roster" + NL + NL + "- Fields are separated by commas, or by"
             " the --delimiter character when it is given." + NL)
ADD_A_LINE = "add new lines under the line it extends"


def described(place, rewrite):
    """roster edits by a worker that also describes the option in TASK.md,
    by a new line or by rewriting the comma line."""
    code = roster_edits(place)

    def edits(step, n):
        code(step, n)
        if step == "worker.md":
            task = place / "TASK.md"
            if rewrite:
                task.write_text(REWRITTEN, encoding="utf-8")
            else:
                with open(str(task), "a", encoding="utf-8") as f:
                    f.write(APPENDED)
    return edits


def test_every_step_is_told_to_describe_an_addition_in_a_new_line(
        monkeypatch):
    for step in ("planner.md", "tester.md", "worker.md"):
        said = composed(monkeypatch, step)
        assert ADD_A_LINE in said, step
        assert "never rewrite or remove a line the spec has" in said, step
    worker = composed(monkeypatch, "worker.md")
    assert "a rewritten line stops the run for a ruling" in worker


def test_an_added_option_described_in_a_new_spec_line_ends_done(
        tmp_path, monkeypatch):
    roster_place(tmp_path)
    place = tmp_path / "project"
    edits = described(place, rewrite=False)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [PLAN], "tester.md": [TESTER],
                               "worker.md": [BUILT],
                               "reviewer.md": [REVIEWED],
                               "reviewer-runs.md": [REVIEWED]}),
                        edits, "--task", ADDS + ". describe it in TASK.md")
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md"]
    assert code == stops.EXIT_OK
    assert (place / "TASK.md").read_text(encoding="utf-8") == SPEC + APPENDED


def test_a_spec_line_the_shipped_flow_added_is_owed_no_ruling_in_the_handoff(
        tmp_path, monkeypatch):
    roster_place(tmp_path)
    edits = described(tmp_path / "project", rewrite=False)
    _, _, code = go(tmp_path, monkeypatch, "build-feature",
                    plain({"planner.md": [PLAN], "tester.md": [TESTER],
                           "worker.md": [BUILT], "reviewer.md": [REVIEWED],
                           "reviewer-runs.md": [REVIEWED]}),
                    edits, "--task", ADDS + ". describe it in TASK.md")
    assert code == stops.EXIT_OK
    [folder] = folders(tmp_path)
    handoff = (folder / "handoff.md").read_text(encoding="utf-8").split(NL)
    assert "- spec TASK.md +1 -0, lines added only, which spec_files:" \
        " additions allows, no ruling needed" in handoff
    assert not [l for l in handoff if "UNRULED" in l or "rule on spec" in l]


def test_the_same_option_described_by_rewriting_the_line_waits_for_a_ruling(
        tmp_path, monkeypatch):
    roster_place(tmp_path)
    edits = described(tmp_path / "project", rewrite=True)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [PLAN], "tester.md": [TESTER],
                               "worker.md": [BUILT],
                               "reviewer.md": [REVIEWED]}),
                        edits, "--task", ADDS + ". describe it in TASK.md")
    assert code == stops.EXIT_STOP
    assert "reviewer.md" not in asked


def pay_place(tmp_path):
    return a_place(tmp_path / "project", {
        "TASK.md": PAY_SPEC, "pay.py": PAY, "conftest.py": "",
        "tests/test_pay.py": PAY_BASELINE})


def pay_edits(place):
    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_allow_zero.py").write_text(
                ZERO_TEST, encoding="utf-8")
        if step == "worker.md":
            (place / "pay.py").write_text(PAY_ZERO, encoding="utf-8")
            with open(str(place / "TASK.md"), "a", encoding="utf-8") as f:
                f.write("- With --allow-zero, an amount may be 0." + NL)
    return edits


def test_a_literal_planner_stops_an_option_that_switches_off_a_never_line(
        tmp_path, monkeypatch):
    before = pay_place(tmp_path)
    place = tmp_path / "project"
    others = {"tester.md": ("FAILS: TypeError: pay() got an unexpected"
                            " keyword argument 'allow_zero'" + NL
                            + "TEST: tests/test_allow_zero.py" + NL),
              "worker.md": "- pay.py: pay takes allow_zero" + NL}
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        literal("An amount is never 0.", ALLOW_ZERO, True,
                                "pay(0, allow_zero=True) is 0", others),
                        pay_edits(place), "--task", ALLOW_ZERO)
    assert (code, end(tmp_path).cause, asked) == (
        stops.EXIT_STOP, "conflict", ["planner.md"])
    assert unchanged(place, before)


def test_a_literal_planner_stops_a_request_that_rewrites_the_line(
        tmp_path, monkeypatch):
    before = roster_place(tmp_path)
    place = tmp_path / "project"
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        literal("Fields are separated by commas.", REWRITES,
                                False, "fields('a;b') is ['a', 'b']"),
                        roster_edits(place), "--task", REWRITES)
    assert (code, end(tmp_path).cause, asked) == (
        stops.EXIT_STOP, "conflict", ["planner.md"])
    assert unchanged(place, before)


def test_a_request_that_rewrites_the_spec_line_still_stops(tmp_path,
                                                          monkeypatch):
    before = roster_place(tmp_path)
    place = tmp_path / "project"
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [CONTRADICTS],
                               "tester.md": [TESTER]}),
                        roster_edits(place), "--task", REWRITES)
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP
    assert end(tmp_path).cause == "conflict"
    assert unchanged(place, before)


UNTYPED = NL.join([
    "- behaviour: fields('a;b') is ['a', 'b']",
    "  file: roster.py",
    "  spec: contradicts TASK.md:3", ""])
SEND_BACK = "marks spec: contradicts TASK.md:3 and has no CONFLICT line"


def test_a_contradiction_with_no_conflict_line_goes_back_and_is_typed(
        tmp_path, monkeypatch):
    roster_place(tmp_path)
    asked, sent, code = go(tmp_path, monkeypatch, "build-feature",
                           plain({"planner.md": [UNTYPED, CONTRADICTS]}),
                           lambda step, n: None, "--task", REWRITES)
    assert asked == ["planner.md", "planner.md"]
    assert SEND_BACK in " ".join(sent[1].split())
    assert code == stops.EXIT_STOP
    assert end(tmp_path).cause == "conflict"


def test_a_contradiction_with_no_conflict_line_goes_back_and_is_withdrawn(
        tmp_path, monkeypatch):
    roster_place(tmp_path)
    place = tmp_path / "project"
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [UNTYPED, PLAN],
                               "tester.md": [TESTER], "worker.md": [BUILT],
                               "reviewer.md": [REVIEWED],
                               "reviewer-runs.md": [REVIEWED]}),
                        roster_edits(place), "--task", ADDS)
    assert asked == ["planner.md", "planner.md", "tester.md", "worker.md",
                     "reviewer.md", "reviewer-runs.md"]
    assert code == stops.EXIT_OK


def test_a_contradiction_left_untyped_twice_stops_before_the_tester(
        tmp_path, monkeypatch):
    roster_place(tmp_path)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [UNTYPED]}),
                        lambda step, n: None, "--task", REWRITES)
    assert asked == ["planner.md", "planner.md"]
    assert code == stops.EXIT_STOP
    assert end(tmp_path).cause == "gate failed"


class Handed(object):
    """the parts of a run `check_step` reads, after a planner whose plan
    marked a behaviour `spec: contradicts`."""

    def __init__(self, tmp_path, plan):
        self.fm = types.SimpleNamespace(steps=[
            {"role": "planner", "prompt": "planner.md"},
            {"role": "tester", "prompt": "tester.md"}])
        self.produced = {"planner.md": plan}
        self.workdir = tmp_path
        self.proven = {}

    def gates_for(self, step):
        return []

    def writes_for(self, step):
        return ""


def conflict_gate(run, step, said):
    route = types.SimpleNamespace(gate=lambda step, out: "")
    out = types.SimpleNamespace(output=said, meta={})
    run.produced[step] = said
    failed, _ = gating.check_step(run, route, step, out)
    return failed


def test_a_later_step_quoting_the_plans_marked_line_is_not_sent_back(
        tmp_path):
    run = Handed(tmp_path, UNTYPED)
    quoted = "the tests follow the plan:" + NL + UNTYPED
    assert conflict_gate(run, "tester.md", quoted) == ""
    own = quoted + "- behaviour: a blank field is kept" + NL \
        + "  spec: contradicts TASK.md:4" + NL
    assert conflict_gate(run, "tester.md", own) == "conflict"
    assert conflict_gate(Handed(tmp_path, ""), "planner.md", UNTYPED) == \
        "conflict"
