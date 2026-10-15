"""a request that contradicts the spec stops as a conflict, never as a failed
gate.

a step that finds the request and the spec disagree answers `CONFLICT:
<file>:<line> "<the line>"` with `request: <the request's words>` on the next
line (the older one-line `| <words>` form still reads). the runner checks the
quote is at that line as the run found it, then stops the run on cause
`conflict` with the question in handoff.md. a quote that is not there fails
the step. `--resume <id> --answer "override: ..."` runs the step again with
the request winning; `--answer "request: ..."` amends the request and starts
again from the first step that reads it.

the flows are the shipped ones, on fake answers and a real git place.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.providers import cli_provider
from agentweft.runner import engine, prompts, resume, ruling, state, stops

NL = chr(10)
FLOWS = Path(__file__).resolve().parents[1] / "flows"


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_place(where, files):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    git(where, "config", "commit.gpgsign", "false")
    for rel, text in files.items():
        path = where / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return dict((rel, (where / rel).read_bytes()) for rel in files)


def go(tmp_path, monkeypatch, flow, answer, edits, *extra):
    """run `flow` on the place in tmp_path/project. `answer(step, n, prompt)`
    is what the step says on its n-th go; `edits(step, n)` is what it writes
    first. -> (steps asked, prompts sent, exit code)."""
    asked = []
    sent = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        n = asked.count(step)
        asked.append(step)
        sent.append(prompt)
        edits(step, n)
        return answer(step, n, prompt), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(FLOWS)])
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", flow, "--force", "--flows",
                                      str(FLOWS), "--workdir", "project"]
                        + list(extra))
    return asked, sent, engine.main()


def folders(tmp_path):
    runs = tmp_path / "runs"
    return sorted((p for p in runs.iterdir() if p.is_dir()),
                  key=lambda p: resume.order_of(p.name))


def end(tmp_path):
    lines = [l for l in (tmp_path / "runs" / "journal.md")
             .read_text(encoding="utf-8").split(NL) if l.strip()]
    return stops.read(lines[-1])


def unchanged(place, before):
    now = sorted(p.relative_to(place).as_posix() for p in place.rglob("*")
                 if p.is_file() and ".git" not in p.parts
                 and "__pycache__" not in p.parts
                 and ".pytest_cache" not in p.parts)
    return now == sorted(before) and all(
        (place / rel).read_bytes() == data for rel, data in before.items())


# build-feature: the request asks for what TASK.md rules out

SPEC = ("# report" + NL + NL
        + "the report lists students alphabetically, by name." + NL)
REPORT = "def report(names):" + NL + "    return sorted(names)" + NL
BASELINE = ("from report import report" + NL + NL + NL
            + "def test_alphabetical():" + NL
            + "    assert report(['b', 'a']) == ['a', 'b']" + NL)
REQUEST = ("report should list the students in the order of the roster file,"
           " not alphabetically")
CONFLICT = ('CONFLICT: TASK.md:3 "the report lists students alphabetically" | '
            + REQUEST + NL)
PLAN = "- report(['b', 'a']) is ['b', 'a'] | report.py" + NL
TESTER = "FAILS: assert ['a', 'b'] == ['b', 'a']" + NL + \
    "TEST: tests/test_roster.py" + NL
ROSTER = ("def test_roster_order():" + NL + "    from report import report"
          + NL + NL + "    assert report(['b', 'a']) == ['b', 'a']" + NL)


def feature_place(tmp_path):
    return a_place(tmp_path / "project", {
        "TASK.md": SPEC, "report.py": REPORT, "conftest.py": "",
        "tests/test_report.py": BASELINE})


def feature_edits(place):
    def edits(step, n):
        # what a step that went along with the request would write
        if step == "tester.md":
            (place / "tests" / "test_roster.py").write_text(
                ROSTER, encoding="utf-8")
            (place / "tests" / "test_report.py").write_text(
                BASELINE.replace("['a', 'b']", "['b', 'a']"),
                encoding="utf-8")
        if step == "worker.md":
            (place / "report.py").write_text(
                "def report(names):" + NL + "    return list(names)" + NL,
                encoding="utf-8")
    return edits


def plain(said):
    def answer(step, n, prompt):
        got = said.get(step, [""])
        return got[min(n, len(got) - 1)]
    return answer


def test_a_build_feature_request_against_the_spec_stops_before_the_tester(
        tmp_path, monkeypatch):
    before = feature_place(tmp_path)
    place = tmp_path / "project"
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [CONFLICT],
                               "tester.md": [TESTER],
                               "worker.md": ["- report.py: roster order" + NL],
                               "reviewer.md": ["VERDICT: ok" + NL]}),
                        feature_edits(place), "--task", REQUEST)
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP
    assert unchanged(place, before)
    line = end(tmp_path)
    assert line.cause == "conflict"
    assert line.status == "stopped at planner.md"
    [folder] = folders(tmp_path)
    kept = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert kept["outcome"] == "stopped: spec conflict"
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    assert handoff.split(NL)[0].startswith(
        "# build-feature " + folder.name + ": stopped: spec conflict at "
        "planner.md")
    assert "TASK.md:3" in handoff
    assert "the report lists students alphabetically" in handoff
    assert '--answer "override: ' in handoff and '--answer "request: ' in handoff
    question = (folder / "question.md").read_text(encoding="utf-8")
    assert "TASK.md:3" in question and REQUEST in question


def test_a_misquoted_conflict_fails_the_step(tmp_path, monkeypatch):
    feature_place(tmp_path)
    place = tmp_path / "project"
    wrong = CONFLICT.replace("TASK.md:3", "TASK.md:1")
    asked, sent, code = go(tmp_path, monkeypatch, "build-feature",
                           plain({"planner.md": [wrong],
                                  "tester.md": [TESTER]}),
                           feature_edits(place), "--task", REQUEST)
    assert "tester.md" not in asked
    assert asked == ["planner.md", "planner.md"]
    assert code == stops.EXIT_STOP
    line = end(tmp_path)
    assert line.cause == "gate failed"
    assert "TASK.md:1" in line.why
    # the second go is told what was wrong with the first
    assert "TASK.md:1" in sent[1]


def test_the_quote_is_checked_against_the_spec_as_the_run_found_it(
        tmp_path, monkeypatch):
    feature_place(tmp_path)
    place = tmp_path / "project"
    quoted = CONFLICT.replace("TASK.md:3", "TASK.md:1")

    def edits(step, n):
        if step == "planner.md":
            # the line is there now because the step wrote it there
            (place / "TASK.md").write_text(
                "the report lists students alphabetically" + NL + SPEC,
                encoding="utf-8")

    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [quoted],
                               "tester.md": [TESTER]}),
                        edits, "--task", REQUEST)
    assert "tester.md" not in asked
    assert end(tmp_path).cause == "gate failed"


def test_override_runs_the_step_again_with_the_spec_line_authorised(
        tmp_path, monkeypatch):
    feature_place(tmp_path)
    place = tmp_path / "project"
    go(tmp_path, monkeypatch, "build-feature", plain({"planner.md": [CONFLICT]}),
       feature_edits(place), "--task", REQUEST)
    [first] = folders(tmp_path)
    asked, sent, _ = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [PLAN]}), lambda s, n: None,
                        "--resume", first.name,
                        "--answer", "override: roster order wins")
    assert asked[:1] == ["planner.md"]
    told = sent[0] if sent else ""
    assert "override: roster order wins" in told
    assert "TASK.md:3" in told[told.find("override: roster order wins"):]
    [ruled] = decisions.read(place)
    assert "override: roster order wins" in ruled.decided
    assert "TASK.md:3" in ruled.why


def test_a_bare_answer_to_a_conflict_is_refused(tmp_path, monkeypatch,
                                                capsys):
    feature_place(tmp_path)
    place = tmp_path / "project"
    go(tmp_path, monkeypatch, "build-feature", plain({"planner.md": [CONFLICT]}),
       feature_edits(place), "--task", REQUEST)
    [first] = folders(tmp_path)
    capsys.readouterr()
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [PLAN]}), lambda s, n: None,
                        "--resume", first.name, "--answer", "roster order")
    assert code == 1 and asked == []
    printed = capsys.readouterr().out
    assert "override:" in printed and "request:" in printed
    assert folders(tmp_path) == [first]


# fix-with-test: the bug report contradicts the spec, and a baseline test in
# the same file pins the spec, so the file cannot go green

EXPORT_SPEC = ("# export" + NL
               + "in the JSON export, `amount` is a string with 2 decimals." + NL)
EXPORT = ("import json" + NL + NL + NL + "def export(amount):" + NL
          + "    return json.dumps({'amount': '%.2f' % amount})" + NL)
EXPORT_TEST = ("import json" + NL + NL + "from export import export" + NL
               + NL + NL + "def test_export_json():" + NL
               + "    assert json.loads(export(-25))['amount'] == '-25.00'" + NL)
NUMBERS = (NL + NL + "def test_amount_is_a_number():" + NL
           + "    assert json.loads(export(-25))['amount'] == -25" + NL)
BUG = ("Bug report: export writes amounts as strings. Amounts in the JSON"
       " export must be JSON numbers.")
WORKER = ("FAILS: assert '-25.00' == -25" + NL
          + "TEST: tests/test_export.py::test_amount_is_a_number" + NL)
PATCHER_CONFLICT = ('CONFLICT: TASK.md:2 "`amount` is a string with 2 decimals"'
                    ' | Amounts in the JSON export must be JSON numbers' + NL)


def bug_place(tmp_path):
    return a_place(tmp_path / "project", {
        "TASK.md": EXPORT_SPEC, "export.py": EXPORT, "conftest.py": "",
        "tests/test_export.py": EXPORT_TEST})


def bug_edits(place):
    def edits(step, n):
        if step == "worker.md":
            (place / "tests" / "test_export.py").write_text(
                EXPORT_TEST + NUMBERS, encoding="utf-8")
    return edits


def test_a_patcher_held_by_a_spec_pinned_test_ends_on_a_conflict(
        tmp_path, monkeypatch):
    before = bug_place(tmp_path)
    place = tmp_path / "project"
    asked, _, code = go(tmp_path, monkeypatch, "fix-with-test",
                        plain({"worker.md": [WORKER],
                               "patcher.md": [PATCHER_CONFLICT]}),
                        bug_edits(place), "--task", BUG)
    assert asked == ["worker.md", "patcher.md"]
    assert code == stops.EXIT_STOP
    line = end(tmp_path)
    assert (line.cause, line.status) == ("conflict", "stopped at patcher.md")
    [folder] = folders(tmp_path)
    kept = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert kept["outcome"] == "stopped: spec conflict"
    assert (place / "export.py").read_bytes() == before["export.py"]


def test_a_red_supplied_test_marked_conflict_is_a_stop_not_a_loop_target(
        tmp_path, monkeypatch):
    bug_place(tmp_path)
    place = tmp_path / "project"
    marked = WORKER + PATCHER_CONFLICT
    asked, _, code = go(tmp_path, monkeypatch, "fix-with-test",
                        plain({"worker.md": [marked],
                               "patcher.md": ["TEST: x" + NL]}),
                        bug_edits(place), "--task", BUG)
    assert asked == ["worker.md"]
    assert end(tmp_path).cause == "conflict"


def test_request_amends_the_task_and_starts_at_the_first_step_that_reads_it(
        tmp_path, monkeypatch):
    bug_place(tmp_path)
    place = tmp_path / "project"
    go(tmp_path, monkeypatch, "fix-with-test",
       plain({"worker.md": [WORKER], "patcher.md": [PATCHER_CONFLICT]}),
       bug_edits(place), "--task", BUG)
    [first] = folders(tmp_path)
    amended = "request: keep strings, and add a --numbers flag for numbers"
    asked, sent, _ = go(tmp_path, monkeypatch, "fix-with-test",
                        plain({}), lambda s, n: None,
                        "--resume", first.name, "--answer", amended)
    assert asked[:1] == ["worker.md"]
    told = sent[0] if sent else ""
    assert BUG in told and "add a --numbers flag for numbers" in told
    second = folders(tmp_path)[-1]
    kept = (second / "task.md").read_text(encoding="utf-8")
    assert kept.startswith(BUG) and "add a --numbers flag" in kept
    [ruled] = decisions.read(place)
    assert "request:" in ruled.decided


# the pieces


def test_conflict_is_a_cause_of_its_own():
    assert "conflict" in stops.CAUSES
    assert stops.outcome("conflict") == "stopped: spec conflict"
    assert stops.exit_code("conflict") == stops.EXIT_STOP
    assert stops.status("conflict", "planner.md") == "stopped at planner.md"


def test_a_conflict_inside_a_code_fence_is_not_one(tmp_path):
    (tmp_path / "TASK.md").write_text(SPEC, encoding="utf-8")
    fenced = "```" + NL + CONFLICT + "```" + NL
    assert hasattr(ruling, "conflict_of")
    assert ruling.conflict_of(fenced, tmp_path) is None
    assert ruling.conflict_of(CONFLICT, tmp_path)[1] == ""


def test_a_quote_across_a_cited_range_is_read_as_one_line(tmp_path):
    (tmp_path / "TASK.md").write_text(
        "pN is the nearest-rank" + NL + "percentile of the values" + NL,
        encoding="utf-8")
    said = 'CONFLICT: TASK.md:1-2 "nearest-rank percentile" | like numpy'
    assert hasattr(ruling, "conflict_of")
    assert ruling.conflict_of(said, tmp_path)[1] == ""
    assert ruling.conflict_of(said.replace("1-2", "2"), tmp_path)[1]


def test_the_request_words_go_on_the_next_line(tmp_path):
    (tmp_path / "TASK.md").write_text(SPEC, encoding="utf-8")
    said = ('CONFLICT: TASK.md:3 "the report lists students alphabetically"'
            + NL + "request: " + REQUEST + NL)
    question, wrong = ruling.conflict_of(said, tmp_path)
    assert wrong == ""
    assert '- the request - "' + REQUEST + '"' in question
    # the old one-line form still reads
    assert REQUEST in ruling.conflict_of(CONFLICT, tmp_path)[0]


def test_a_request_line_away_from_the_conflict_is_not_its_words(tmp_path):
    (tmp_path / "TASK.md").write_text(SPEC, encoding="utf-8")
    said = ('request: something else' + NL + NL
            + 'CONFLICT: TASK.md:3 "the report lists students alphabetically"'
            + NL)
    assert "something else" not in ruling.conflict_of(said, tmp_path)[0]


def test_no_prompt_teaches_the_one_line_form():
    for flow, step in (("build-feature", "instructions.md"),
                       ("fix-with-test", "worker.md"),
                       ("fix-with-test", "patcher.md")):
        text = (FLOWS / flow / step).read_text(encoding="utf-8")
        assert '" | <the' not in text, flow + "/" + step
        assert "request: <the request's words>" in text \
            or "request: <the report's words>" in text, flow + "/" + step


def test_build_feature_calls_the_request_the_request_and_the_spec_task_md():
    words = " ".join((FLOWS / "build-feature" / "instructions.md").read_text(
        encoding="utf-8").split())
    assert "the request:" in words and "the spec:" not in words
    assert "TASK.md" in words
    planner = " ".join((FLOWS / "build-feature" / "planner.md").read_text(
        encoding="utf-8").split())
    assert "CONFLICT:" in planner and "allows" in planner \
        and "contradicts" in planner


def test_every_step_that_reads_the_request_is_told_the_conflict_answer():
    for flow, step in (("build-feature", "tester.md"),
                       ("build-feature", "worker.md"),
                       ("fix-with-test", "worker.md"),
                       ("fix-with-test", "patcher.md")):
        text = (FLOWS / flow / step).read_text(encoding="utf-8")
        assert "CONFLICT:" in text, flow + "/" + step
