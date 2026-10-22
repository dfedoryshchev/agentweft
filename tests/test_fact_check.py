"""a fact can carry a check, and a change in its scope that breaks it is
said in the handoff.

the check is a grep the runner runs itself on the files in the fact's scope,
never a process, so a check a model proposed or a cloned project carried
cannot run anything. it has to hold on the tree when the fact is written.
after a step that changed a file in the fact's scope it runs again: held,
broken or could not run, on the step's line in steps.jsonl and in the
handoff. a broken check warns by default and the run goes on;
`conformance: fail` makes it a gate that sends the step back. a check that
cannot run is said, never counted a pass."""
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.guardrails import factsguard
from agentweft.orchestrate import facts
from agentweft.runner import engine
from test_stops import a_flow, steps_of, the_folder

NL = chr(10)
CODE = NL.join(["import sys", "", "def parse(line):", "    if not line:",
                "        raise ValueError('empty')", "    return line.split()",
                ""])
PRINTS = CODE.replace("raise ValueError('empty')",
                      "print('error: empty')" + NL + "        return []")
CHECK = 'grep -n "print(" pkg/parse.py exits 1'


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def entry(id, scope, check, claim="parse raises, it never prints"):
    return NL.join(["## " + id + " live", "scope: " + scope,
                    "kind: convention", "claim: " + claim,
                    "why: one error line on stderr, printed by cli.py",
                    "source: run r-1 step worker.md seq 2; evidence:"
                    ' pkg/parse.py:5 "raise ValueError"',
                    "check: " + check]) + NL


# --- the check itself -----------------------------------------------------


def test_a_grep_check_holds_on_clean_lines_and_breaks_where_it_matches(
        tmp_path):
    put(tmp_path, "pkg/parse.py", CODE)
    assert facts.run_check(tmp_path, CHECK) == (True, "")
    put(tmp_path, "pkg/parse.py", PRINTS)
    held, said = facts.run_check(tmp_path, CHECK)
    assert held is False
    assert said == ("grep exits 0, the fact says 1: pkg/parse.py:5:"
                    "        print('error: empty')")


@pytest.mark.parametrize("check,held", [
    ('grep -n "print(" pkg/parse.py', False),
    ('grep "raise ValueError(" pkg/parse.py exits 0', True),
    ('grep -E "raise (Value|Type)Error" pkg/parse.py', True),
    ('grep -F "split()" pkg/parse.py', True),
    ('grep -i "VALUEERROR" pkg/parse.py', True),
    ('grep -w "pars" pkg/parse.py exits 1', True),
    ('grep -rn "print(" pkg --include=*.py exits 1', True),
    ('grep -rn "print(" pkg exits 1', False),
    ('grep -rn "print(" . --include=*.md exits 1', True),
    ("grep -n 'line\\.split' pkg/parse.py", True),
    ('grep "\\<parse\\>" pkg/parse.py', True),
    ('grep -E "\\<line\\>" pkg/parse.py', True),
    ('grep "\\<pars\\>" pkg/parse.py exits 1', True),
    ('grep "\\bsplit\\b" pkg/parse.py', True),
    ('grep "\\w\\+Error" pkg/parse.py', True),
    ('grep "[\\]" pkg/parse.py exits 1', True),
])
def test_a_check_reads_its_pattern_and_paths_the_way_grep_does(tmp_path,
                                                               check, held):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "pkg/notes.txt", "print(" + NL)
    put(tmp_path, "facts/pkg/parse.py.md", entry("F-0001", "pkg/", CHECK))
    assert facts.run_check(tmp_path, check)[0] is held, check


@pytest.mark.parametrize("check,why", [
    ("rm -rf pkg", "only a grep"),
    ("python -c 'print(1)'", "only a grep"),
    ('grep -n "x" ../outside.py', "not in the place"),
    ('grep -n "x" pkg/missing.py', "pkg/missing.py is not a file"),
    ('grep -n "x" pkg', "pkg is a folder"),
    ('grep -z "x" pkg/parse.py', "-z"),
    ('grep -E -n "(" pkg/parse.py', "the pattern"),
    ('grep -n "x" pkg/parse.py exits maybe', "exits"),
    ('grep -n "x"', "no file"),
    ('grep -n "x" pkg/parse.py; rm -rf pkg', "is not a path"),
    ('grep -E "raise \\d" pkg/parse.py', "\\d"),
    ('grep "line\\d" pkg/parse.py exits 1', "\\d"),
    ('grep "\\Aimport" pkg/parse.py', "\\A"),
])
def test_a_check_that_cannot_run_is_never_a_pass(tmp_path, check, why):
    put(tmp_path, "pkg/parse.py", CODE)
    held, said = facts.run_check(tmp_path, check)
    assert held is None, check
    assert said.startswith("could not run: ") and why in said, said


def test_an_absolute_path_is_not_in_the_place(tmp_path):
    put(tmp_path, "pkg/parse.py", CODE)
    held, said = facts.run_check(
        tmp_path, 'grep -n "x" ' + (tmp_path / "pkg" / "parse.py").as_posix())
    assert held is None and "not in the place" in said


def test_a_check_starts_no_process(tmp_path, monkeypatch):
    def refused(*a, **kw):
        raise AssertionError("a fact's check started a process")

    monkeypatch.setattr(subprocess, "run", refused)
    monkeypatch.setattr(subprocess, "Popen", refused)
    put(tmp_path, "pkg/parse.py", PRINTS)
    assert facts.run_check(tmp_path, CHECK)[0] is False


# --- written only when it holds -------------------------------------------


def proposal(check, scope="pkg/parse.py"):
    return factsguard.Proposal({
        "scope": [scope], "kind": "convention", "label": "none",
        "claim": "parse raises, it never prints",
        "why": "one error line on stderr, printed by cli.py",
        "source": 'seq 2 worker.md; evidence: pkg/parse.py:3 "def'
                  ' parse(line)"',
        "check": check})


def a_store(tmp_path, code=CODE):
    put(tmp_path, "pkg/parse.py", code)
    put(tmp_path, "pkg/cli.py", "print('x')" + NL)
    return factsguard.Store(tmp_path), factsguard.Record(tmp_path)


def test_a_fact_whose_check_holds_is_written_with_it(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(CHECK), record)
    assert why == ""
    assert fact.get("check") == CHECK


def test_a_fact_whose_check_does_not_hold_on_the_tree_is_refused(tmp_path):
    store, record = a_store(tmp_path, PRINTS)
    fact, why = store.add(proposal(CHECK), record)
    assert fact is None
    assert why.startswith("the check does not hold on the tree as it is:"
                          " grep exits 0, the fact says 1")


def test_a_fact_whose_check_cannot_run_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal("pytest -q tests"), record)
    assert fact is None
    assert why.startswith("the check cannot run: ")


def test_a_check_that_reads_outside_the_facts_scope_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal('grep -n "print(" pkg/cli.py exits 0'),
                          record)
    assert fact is None
    assert why == ("the check reads pkg/cli.py, which is not in the fact's"
                   " scope")


# --- run after a step that changes the scope ------------------------------


def fake_flow(tmp_path, monkeypatch, writes, head=""):
    replies = ["provider:", "  provider: fake", "  replies:",
               "    worker.md:", "      - say: |", "          changed it",
               "        writes:", "          pkg/parse.py: |"]
    replies.extend("            " + l for l in writes.split(NL)[:-1])
    replies.extend(["    notes.md:", "      - say: |",
                    "          noted"])
    a_flow(tmp_path, monkeypatch, "facts", ["worker", "notes"],
           tail=head + NL.join(replies) + NL)


def a_place(tmp_path):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "pkg/cli.py", "import sys" + NL)
    put(tmp_path, "facts/pkg/parse.py.md", entry("F-0001", "pkg/parse.py",
                                                 CHECK))


def test_a_step_that_breaks_a_facts_check_gets_a_conformance_line_and_the_run_goes_on(
        tmp_path, monkeypatch):
    a_place(tmp_path)
    fake_flow(tmp_path, monkeypatch, PRINTS)
    assert engine.main() == 0
    worker, notes = steps_of(the_folder())[:2]
    assert worker["conformance"] == [{
        "fact": "F-0001", "scope": ["pkg/parse.py"],
        "claim": "parse raises, it never prints", "check": CHECK,
        "result": "broken",
        "said": "grep exits 0, the fact says 1: pkg/parse.py:5:"
                "        print('error: empty')"}]
    assert "conformance" not in notes
    assert all(g["gate"] != "conformance" for g in worker["gates"])
    text = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    view = text.split("## full record")[0]
    assert "a fact's check broken at the end of the run:" in view
    assert ("- F-0001 on pkg/parse.py, broken by worker.md: parse raises, it"
            " never prints") in view
    assert "## conformance" in text
    assert ("- worker.md: F-0001 (pkg/parse.py) broken: " + CHECK
            + " - grep exits 0, the fact says 1") in text
    [fact] = facts.read(tmp_path)
    assert "contradicted 1" in fact.get("seen")


def test_a_step_that_keeps_a_facts_check_is_counted_as_honouring_it(
        tmp_path, monkeypatch):
    a_place(tmp_path)
    fake_flow(tmp_path, monkeypatch, CODE.replace("split()", "split(' ')"))
    assert engine.main() == 0
    [worker] = steps_of(the_folder())[:1]
    assert [c["result"] for c in worker["conformance"]] == ["held"]
    text = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    assert "a fact's check broken" not in text
    assert "- worker.md: F-0001 (pkg/parse.py) held: " + CHECK in text
    [fact] = facts.read(tmp_path)
    assert "honoured 1" in fact.get("seen")


def test_a_step_that_leaves_the_scope_alone_runs_no_check(tmp_path,
                                                         monkeypatch):
    a_place(tmp_path)
    put(tmp_path, "pkg/parse.py", PRINTS)
    fake_flow(tmp_path, monkeypatch, PRINTS)
    assert engine.main() == 0
    assert all("conformance" not in l for l in steps_of(the_folder()))


def test_with_conformance_fail_a_broken_check_sends_the_step_back(
        tmp_path, monkeypatch):
    a_place(tmp_path)
    fake_flow(tmp_path, monkeypatch, PRINTS, head="conformance: fail" + NL)
    assert engine.main() != 0
    lines = steps_of(the_folder())
    worker = lines[0]
    assert (worker["outcome"], worker["to"]) == ("gate failed", "worker.md")
    again = lines[1]
    assert again["step"] == "worker.md"
    assert [c["result"] for c in again["conformance"]] == ["broken"]
    [gate] = [g for g in worker["gates"] if g["gate"] == "conformance"]
    assert gate["ok"] is False
    assert gate["detail"].startswith("F-0001 on pkg/parse.py: parse raises,"
                                     " it never prints; " + CHECK)


def test_with_conformance_fail_a_broken_check_holds_on_a_resumed_leg(
        tmp_path, monkeypatch):
    a_place(tmp_path)
    fake_flow(tmp_path, monkeypatch, PRINTS, head="conformance: fail" + NL)
    assert engine.main() != 0
    first = the_folder()
    monkeypatch.setattr(sys, "argv", ["run.py", "facts", "--force",
                                      "--resume", first.name])
    assert engine.main() != 0
    [later] = [p for p in first.parent.iterdir()
               if p.is_dir() and p != first]
    worker = steps_of(later)[0]
    assert worker["step"] == "worker.md"
    assert [c["result"] for c in worker["conformance"]] == ["broken"]
    assert [g["ok"] for g in worker["gates"]
            if g["gate"] == "conformance"] == [False]


def test_a_hand_written_check_outside_its_scope_cannot_run_after_a_step(
        tmp_path):
    a_place(tmp_path)
    put(tmp_path, "facts/pkg/parse.py.md", entry(
        "F-0001", "pkg/parse.py", 'grep -n "print(" pkg/cli.py exits 1'))
    store = factsguard.Store(tmp_path)
    put(tmp_path, "pkg/parse.py", PRINTS)
    [line] = store.conform()
    assert line["result"] == "could not run"
    assert line["said"] == ("could not run: the check reads pkg/cli.py, which"
                            " is not in the fact's scope")


def test_a_fresh_run_does_not_hold_a_step_to_a_break_it_found(
        tmp_path, monkeypatch):
    a_place(tmp_path)
    put(tmp_path, "pkg/parse.py", PRINTS)
    fake_flow(tmp_path, monkeypatch, PRINTS, head="conformance: fail" + NL)
    assert engine.main() == 0
    assert all("conformance" not in l for l in steps_of(the_folder()))


def test_a_check_that_could_not_run_after_a_step_is_said_never_passed(
        tmp_path, monkeypatch):
    a_place(tmp_path)
    put(tmp_path, "facts/pkg/parse.py.md", entry(
        "F-0001", "pkg/", 'grep -n "print(" pkg/gone.py exits 1'))
    fake_flow(tmp_path, monkeypatch, PRINTS)
    assert engine.main() == 0
    [line] = steps_of(the_folder())[0]["conformance"]
    assert line["result"] == "could not run"
    text = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    assert "F-0001 on pkg/, its check could not run after worker.md" in text
    [fact] = facts.read(tmp_path)
    assert "honoured 0" in fact.get("seen") or "honoured" not in fact.get(
        "seen")


def test_the_retro_is_taught_the_check_a_fact_can_carry():
    from agentweft.roles import resolver

    skill = resolver.skill("retro")
    assert 'check: <optional: grep "<pattern>"' in skill
    assert "refuses a fact whose check does not hold now" in skill


def test_the_retro_is_handed_each_check_a_step_broke(tmp_path):
    from agentweft.runner import retro

    line = {"seq": 3, "step": "worker.md", "conformance": [
        {"fact": "F-0001", "result": "broken", "check": CHECK,
         "said": "grep exits 0, the fact says 1"},
        {"fact": "F-0002", "result": "held", "check": CHECK, "said": ""}]}
    assert retro.unheld([(line, tmp_path)]) == [
        "- seq 3 worker.md: F-0001 broken: " + CHECK
        + " - grep exits 0, the fact says 1"]


def test_the_flow_key_is_warn_or_fail():
    assert "conformance" in spec.KNOWN
    assert spec.check({"name": "x", "steps": [{"role": "w"}],
                       "conformance": "warn"}) == []
    assert spec.check({"name": "x", "steps": [{"role": "w"}],
                       "conformance": "fail"}) == []
    assert spec.check({"name": "x", "steps": [{"role": "w"}],
                       "conformance": "block"}) == [
        "conformance should be warn or fail"]
