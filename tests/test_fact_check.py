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
    ('grep -rn "print(" pkg --include=*.txt exits 0', True),
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
    ('grep -rn "print(" . --include=*.md exits 1', "it read no file"),
    ('grep -rn "print(" pkg --include=*.nomatch exits 1', "it read no file"),
    ('grep -rn "print(" pkg --include=*.nomatch exits 0', "it read no file"),
    ('grep -rn "print(" empty exits 1', "it read no file"),
    ('grep -rn "print(" empty exits 0', "it read no file"),
])
def test_a_check_that_cannot_run_is_never_a_pass(tmp_path, check, why):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "facts/pkg/parse.py.md", entry("F-0001", "pkg/", CHECK))
    (tmp_path / "empty").mkdir()
    held, said = facts.run_check(tmp_path, check)
    assert held is None, check
    assert said.startswith("could not run: ") and why in said, said


@pytest.mark.parametrize("claim, check, kind", [
    ("every line of parse raises rather than prints",
     'grep -rn "print(" pkg --include=*.nomatch exits 1', "convention"),
    ("parse raises ValueError on an empty line",
     'grep -rn "raise" pkg --include=*.nomatch exits 0', "decision"),
    ("parse never prints", 'grep -rn "print(" pkg/empty/ exits 1',
     "convention")])
def test_a_check_that_reads_no_file_refuses_its_fact(tmp_path, claim, check,
                                                     kind):
    store, record = a_store(tmp_path)
    (tmp_path / "pkg" / "empty").mkdir()
    p = claimed(claim, check, kind)
    p.fields["scope"] = ["pkg/"]
    fact, why = store.add(p, record)
    assert fact is None, fact.get("unchecked")
    assert why.startswith("the check reads no file, so it shows nothing of"
                          " the claim"), why


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


FOUND = 'grep -n -F "raise ValueError" pkg/parse.py exits 0'


def claimed(claim, check=None, kind="convention"):
    p = proposal(check or "")
    p.fields.update(claim=claim, kind=kind)
    return p


@pytest.mark.parametrize("claim, word", [
    ("every caller of parse gets a ValueError on an empty line", "every"),
    ("parse never prints", "never"),
    ("Each command checks its options before it reads a file", "each")])
def test_a_convention_that_says_every_or_never_with_no_check_is_refused(
        tmp_path, claim, word):
    store, record = a_store(tmp_path)
    fact, why = store.add(claimed(claim), record)
    assert fact is None
    assert why == ("a convention that says " + word + " is kept only with a"
                   " check that holds on the tree, and it has none")


def test_a_convention_that_says_every_held_by_one_matching_line_is_refused(
        tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(claimed("every empty line raises ValueError",
                                  FOUND), record)
    assert fact is None
    assert why == ("a convention that says every is kept only with a check"
                   " that holds on the tree: an exits 0 grep holds by one"
                   " line, never by every one; it needs a pattern no line"
                   " may match, exits 1")


@pytest.mark.parametrize("claim, word", [
    ("parse is the only place an empty line is refused", "only"),
    ("a single function, parse, refuses an empty line", "single"),
    ("parse is the sole caller of split", "sole"),
    ("parse raises on any empty line", "any"),
    ("no caller of parse prints the error", "no"),
    ("No command reads a file before parse", "no"),
    ("none of the callers print", "none"),
    ("None of the callers print", "none")])
def test_a_convention_that_says_only_any_or_no_is_universal_too(
        tmp_path, claim, word):
    store, record = a_store(tmp_path)
    fact, why = store.add(claimed(claim, FOUND), record)
    assert fact is None
    assert why.startswith("a convention that says " + word + " is kept only"
                          " with a check that holds on the tree: an exits 0"
                          " grep holds by one line"), why


@pytest.mark.parametrize("claim", [
    "parse returns None for an empty line",
    "parse returns `None` for a blank line, and `--no-strict` keeps it",
    "parse raises ValueError, and a caller no longer checks the line first",
    "parse is a no-op on a line it already split",
    "parse raises ValueError (see `all_lines`)"])
def test_python_none_a_flag_and_a_word_part_are_not_universal_words(
        tmp_path, claim):
    store, record = a_store(tmp_path)
    fact, why = store.add(claimed(claim, FOUND), record)
    assert why == "" and fact is not None


@pytest.mark.parametrize("claim, check, kind", [
    ("parse never prints", CHECK, "convention"),
    ("parse raises ValueError on an empty line", None, "convention"),
    ("parse allocates its words with split", None, "convention"),
    ("every caller counts on the raise", None, "why"),
    ("parse raises only because the caller prints", None, "why"),
    ("no test pins which of two errors wins", None, "decision"),
    ("parse checks the line only per call, so any caller can skip it", None,
     "defect"),
    ("parse raises ValueError on an empty line", FOUND, "convention")])
def test_a_fact_that_claims_no_every_or_never_or_holds_it_is_written(
        tmp_path, claim, check, kind):
    store, record = a_store(tmp_path)
    fact, why = store.add(claimed(claim, check, kind), record)
    assert why == "" and fact is not None


DECIDED = "parse must raise on an empty line, so the caller prints it once"


@pytest.mark.parametrize("check, refused", [
    ('grep -n "raise" pkg/cli.py exits 1',
     "the check reads pkg/cli.py, which is not in the fact's scope"),
    ("pytest -q tests", "the check cannot run: only a grep runs as a fact's"
                        " check, never pytest"),
    ('grep -n -E "print\\(|echo" pkg/parse.py exits 1',
     "the check holds a pipe character, which no taught format carries"),
    ('grep -n -E "print(|echo" pkg/parse.py exits 1',
     "the check cannot run: the pattern does not read: missing ), unterminated"
     " subpattern at position 5")])
def test_a_true_fact_refused_only_for_its_check_is_kept_without_it(
        tmp_path, check, refused):
    store, record = a_store(tmp_path)
    fact, why = store.add(claimed(DECIDED, check, "decision"), record)
    assert why == "" and fact is not None
    assert fact.get("check") == ""
    assert fact.get("unchecked") == "its check was refused: " + refused
    [kept] = facts.read(tmp_path)
    assert kept.get("unchecked") == fact.get("unchecked")
    assert "|" not in (tmp_path / "facts" / "pkg" / "parse.py.md").read_text(
        encoding="utf-8")


@pytest.mark.parametrize("claim, check, kind, refused", [
    (DECIDED, CHECK, "decision", "the check does not hold on the tree"),
    ("parse raises, it never prints", 'grep -n "zzz" pkg/cli.py exits 1',
     "convention", "the check reads pkg/cli.py"),
    ("parse raises, it never prints", 'grep -E "zzz|yyy" pkg/parse.py exits 1',
     "convention", "check holds a |, which no taught format carries"),
    (DECIDED, 'grep -n "sk-' + "a1B2" * 6 + '" pkg/parse.py exits 1',
     "decision", "it looks like a secret")])
def test_a_check_that_breaks_a_secret_or_an_every_claim_still_refuses_it(
        tmp_path, claim, check, kind, refused):
    store, record = a_store(tmp_path, PRINTS)
    fact, why = store.add(claimed(claim, check, kind), record)
    assert fact is None and why.startswith(refused), why


@pytest.mark.parametrize("check", [
    'grep -n -E "raise|echo" pkg/parse.py exits 1',
    'grep -rn "raise" pkg/ exits 1',
    'grep -rn -E "raise|echo" pkg exits 1'])
def test_a_check_refused_for_its_form_that_runs_and_breaks_refuses_the_fact(
        tmp_path, check):
    store, record = a_store(tmp_path)
    fact, why = store.add(claimed("parse prints its error and returns, it"
                                  " does not raise", check, "decision"), record)
    assert fact is None, fact.get("unchecked")
    assert why.startswith("the check does not hold on the tree as it is: grep"
                          " exits 0, the fact says 1: pkg/parse.py:5:"), why


PINNED = ("the check only finds the fact's own anchored line, pkg/parse.py:5,"
          " so it holds the code's text, not the claim")


@pytest.mark.parametrize("kind, check", [
    ("decision", FOUND),
    ("convention", FOUND),
    ("why", 'grep -n -w "ValueError" pkg/parse.py exits 0'),
    ("why", 'grep -n "raise ValueError(.empty.)" pkg/parse.py exits 0')])
def test_a_check_that_only_greps_the_facts_own_anchored_line_is_refused(
        tmp_path, kind, check):
    store, record = a_store(tmp_path)
    p = claimed("parse raises ValueError on an empty line", check, kind)
    p.fields["anchor"] = "pkg/parse.py:3-6"
    fact, why = store.add(p, record)
    assert why == "" and fact is not None
    assert fact.get("check") == ""
    assert fact.get("unchecked") == "its check was refused: " + PINNED


@pytest.mark.parametrize("anchor, check", [
    ("pkg/parse.py:1-2", FOUND),
    ("pkg/parse.py:3-6", 'grep -n "print(" pkg/parse.py exits 1'),
    ("", FOUND)])
def test_a_check_that_finds_more_than_the_anchored_line_is_kept(
        tmp_path, anchor, check):
    store, record = a_store(tmp_path)
    p = claimed("parse raises ValueError on an empty line", check, "decision")
    if anchor:
        p.fields["anchor"] = anchor
    fact, why = store.add(p, record)
    assert why == "" and fact.get("check") == check
    assert fact.get("unchecked") == ""


def test_the_retro_and_a_later_step_are_told_the_check_was_refused(tmp_path):
    from agentweft.runner import brief, upkeep

    store, record = a_store(tmp_path)
    done = upkeep.Maintained()
    upkeep.execute(store, record, [("fact", "", dict(claimed(
        DECIDED, 'grep -n "raise" pkg/cli.py exits 1', "decision").fields))],
        done, "r-1")
    said = ("its check was refused: the check reads pkg/cli.py, which is not"
            " in the fact's scope")
    assert done.lines == ["- wrote F-0001 (pkg/parse.py, decision): " + DECIDED
                          + " (kept without its check; " + said + ")"]
    [fact] = facts.read(tmp_path)
    assert "  unchecked: " + said in brief.Brief(tmp_path).fact_chunk(fact)


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


def test_the_retro_is_told_what_the_store_keeps_and_refuses():
    import re

    from agentweft.roles import resolver

    skill = " ".join(resolver.skill("retro").split())
    assert ("a guard for a defect the run left in place, named by its `F-` id"
            " or by the `seq <n>` its `defect` fact cites, is never written"
            " but proposed") in skill
    said = re.search(r"a convention whose claim says ([a-z, ]+) \(as a word",
                     skill)
    assert said, skill
    words = set(re.findall(r"[a-z]+", said.group(1))) - {"or"}
    assert words == set(factsguard.UNIVERSAL)
    assert ("is kept only with a check a line against it breaks, `exits 1`"
            in skill)
    assert ("a check refused for its form (a `|` in an `-E` pattern, a path"
            " outside the fact's scope) is still run: one that does not hold"
            " refuses the fact, and so does one that reads no file") in skill
    assert ("a fact whose check cannot run, or runs and holds but is refused"
            " for its form, is kept without it, marked `unchecked:`") in skill
    assert "never a `|` outside a check" in skill


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
