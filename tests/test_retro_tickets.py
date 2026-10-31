"""the retro writes no file into the tree. a doc edit or a test it would make
is a `nice-to-do` fact in the store: one file, a change of a few lines, its
evidence and why, for the planner of a later run to fold in."""
import json
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import factsguard
from agentweft.orchestrate import facts
from agentweft.runner import engine, upkeep
from test_retro_maintains import GOOD, block, clean, put
from test_stops import steps_of, the_folder

NL = chr(10)
README = ("# pkg" + NL + NL + "parse returns a list of words." + NL + NL
          + "run it with --words." + NL)
EDIT = NL.join(["edit: README.md", "  now: parse returns a list of words.",
                "  after: `parse` returns a list of words and raises on an"
                " empty line.",
                "  because: the run found the raise undocumented"])
RULED = ("# decisions" + NL + NL + "- 2026-10-30 10:00:00 worker.md: keep the"
         " limit at 10 - the spec says so" + NL)
GUARD = NL.join(["guard: seq 1", "  kind: test",
                 "  where: tests/test_a_guard.py",
                 "  what: an empty line raises ValueError",
                 "  code: from pkg.a import parse", "  code: import pytest",
                 "  code: ", "  code: def test_empty():",
                 "  code:     with pytest.raises(ValueError):",
                 "  code:         parse('')"])


def ticket(scope="pkg/a.py", claim="raise a ValueError naming the line in"
           " parse, not a bare one", extra=()):
    return NL.join(["fact:"] + ["  scope: " + s for s in
                                ([scope] if isinstance(scope, str) else scope)]
                   + ["  kind: nice-to-do", "  claim: " + claim,
                      "  why: the caller prints the error as it is, and an"
                      " empty one says nothing",
                      '  source: seq 1 worker.md; evidence: pkg/a.py:5 "raise'
                      ' ValueError"'] + list(extra))


def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c",
                    "user.name=t", "-c", "commit.gpgsign=false"] + list(args),
                   check=True, capture_output=True)


def last_line():
    return steps_of(the_folder())[-1]


@pytest.mark.parametrize("repo", ["no git", "git, README.md never committed",
                                  "git, README.md committed"])
def test_an_edit_the_retro_asks_for_changes_no_file_in_the_tree(
        tmp_path, monkeypatch, fake_cli, repo):
    put(tmp_path, "README.md", README)
    clean(tmp_path, monkeypatch, fake_cli, block(EDIT))
    if repo != "no git":
        git(tmp_path, "init", "-q")
        git(tmp_path, "add", "README.md" if repo.endswith(" committed")
            and "never" not in repo else "pkg")
        git(tmp_path, "commit", "-qm", "start")
    assert engine.main() == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README
    assert not (last_line().get("facts") or {}).get("applied")


def test_an_edit_to_the_ruling_record_changes_nothing(tmp_path, monkeypatch,
                                                      fake_cli):
    put(tmp_path, "decisions.md", RULED)
    put(tmp_path, "README.md", README)
    clean(tmp_path, monkeypatch, fake_cli, block(NL.join([
        "edit: decisions.md", "  now: keep the limit at 10",
        "  after: raise the limit to `parse`",
        "  because: the run found it"])))
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "start")
    assert engine.main() == 0
    assert (tmp_path / "decisions.md").read_text(encoding="utf-8") == RULED


def test_a_test_guard_writes_no_test_file(tmp_path, monkeypatch, fake_cli):
    clean(tmp_path, monkeypatch, fake_cli, block(GUARD))
    assert engine.main() == 0
    assert not (tmp_path / "tests" / "test_a_guard.py").exists()
    said = (the_folder() / "retro.md").read_text(encoding="utf-8")
    assert upkeep.NO_WRITE in said
    assert "a nice-to-do names the one file it is done in" in said


def test_an_edit_on_one_doc_the_size_of_a_tidy_becomes_a_ticket(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "README.md", README)
    clean(tmp_path, monkeypatch, fake_cli, block(EDIT))
    assert engine.main() == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README
    [fact] = facts.read(tmp_path)
    assert (fact.kind, fact.scopes, fact.status) == (
        "nice-to-do", ["README.md"], "live")
    assert "raises on an empty line" in fact.claim
    assert fact.get("why") == "the run found the raise undocumented"
    assert 'README.md:3 "parse returns a list of words."' in fact.get("source")
    said = last_line()["facts"]
    assert said["written"] == said["tickets"] == [fact.id]
    assert not (tmp_path / "facts" / "PROPOSED.md").is_file()


def test_a_test_guard_on_a_test_file_of_the_place_becomes_a_ticket(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "tests/test_a.py", "def test_one():" + NL + "    pass" + NL)
    clean(tmp_path, monkeypatch, fake_cli, block(GOOD, NL.join([
        "guard: F-0001", "  kind: test", "  where: tests/test_a.py",
        "  what: an empty line raises ValueError",
        "  code: def test_empty():", "  code:     pass"])))
    assert engine.main() == 0
    assert (tmp_path / "tests" / "test_a.py").read_text(encoding="utf-8") \
        == "def test_one():" + NL + "    pass" + NL
    first, tidy = facts.read(tmp_path)
    assert (tidy.kind, tidy.scopes) == ("nice-to-do", ["tests/test_a.py"])
    assert "an empty line raises ValueError" in tidy.claim
    assert tidy.get("source") == first.get("source")
    assert last_line()["facts"]["tickets"] == [tidy.id]


@pytest.mark.parametrize("item, files, why", [
    (EDIT.replace("edit: README.md", "edit: NOTES.md"), {},
     "a nice-to-do names the one file it is done in"),
    (EDIT.replace("raises on an empty line.", "raises on an empty line, "
                  + "and says which line it was, " * 6 + "too."),
     {"README.md": README}, "a task, not a tidy"),
    (EDIT.replace("now: parse returns a list of words.", "now: no such words"),
     {"README.md": README}, '"no such words" is not in README.md'),
    (GUARD, {}, "a nice-to-do names the one file it is done in"),
    (NL.join(["guard: seq 1", "  kind: test", "  where: tests/test_a.py",
              "  what: an empty line raises ValueError"]),
     {"tests/test_a.py": "def test_one():" + NL + "    pass" + NL},
     "the evidence does not hold: it names no evidence"),
    (NL.join(["edit: decisions.md", "  now: keep the limit at 10",
              "  after: keep the limit at 12",
              "  because: the run found it"]), {"decisions.md": RULED},
     "decisions.md is the runner's to write"),
])
def test_an_edit_or_guard_that_cannot_be_a_ticket_is_kept_for_a_person(
        tmp_path, monkeypatch, fake_cli, item, files, why):
    for rel, text in files.items():
        put(tmp_path, rel, text)
    clean(tmp_path, monkeypatch, fake_cli, block(item))
    assert engine.main() == 0
    assert not [f for f in facts.read(tmp_path) if f.kind == "nice-to-do"]
    for rel, text in files.items():
        assert (tmp_path / rel).read_text(encoding="utf-8") == text
    proposed = (tmp_path / "facts" / "PROPOSED.md").read_text(
        encoding="utf-8")
    assert "refused: " + upkeep.NO_WRITE in proposed
    assert why in proposed, proposed
    [refused] = last_line()["facts"]["refused"]
    assert why in refused["why"]


def test_a_nice_to_do_on_one_file_is_kept_as_a_ticket(tmp_path, monkeypatch,
                                                     fake_cli):
    clean(tmp_path, monkeypatch, fake_cli, block(ticket()))
    assert engine.main() == 0
    [fact] = facts.read(tmp_path)
    assert fact.kind == "nice-to-do" and fact.scopes == ["pkg/a.py"]
    assert fact.status == "live"
    assert last_line()["facts"]["written"] == [fact.id]
    assert factsguard.Store(tmp_path).check("next") == ""


@pytest.mark.parametrize("scope, claim, why", [
    ("pkg/", None, "names the one file it is done in"),
    ("pkg/*.py", None, "names the one file it is done in"),
    (".", None, "names the one file it is done in"),
    (["pkg/a.py", "pkg/b.py"], None, "names the one file it is done in"),
    ("pkg/a.py", "refactor parse into a class", "a task, not a tidy"),
    ("pkg/a.py", "move the raise into pkg/b.py", "a task, not a tidy"),
    ("pkg/a.py", "x" * 201, "a task, not a tidy"),
])
def test_a_nice_to_do_wider_than_a_tidy_is_refused(tmp_path, scope, claim,
                                                  why):
    put(tmp_path, "pkg/a.py", NL.join(["import os", "", "def parse(line):",
                                       "    if not line:",
                                       "        raise ValueError('empty')",
                                       "    return line.split()", ""]))
    put(tmp_path, "pkg/b.py", "x = 1" + NL)
    fields = {"scope": scope, "kind": "nice-to-do",
              "claim": claim or "raise a ValueError naming the line",
              "why": "the caller prints it",
              "source": 'seq 1 worker.md; evidence: pkg/a.py:5 "raise'
                        ' ValueError"'}
    store = factsguard.Store(tmp_path)
    fact, said = store.add(factsguard.Proposal(fields),
                           factsguard.Record(tmp_path))
    assert fact is None and why in said, said


def test_tickets_have_a_cap_of_their_own_beside_the_facts(tmp_path):
    put(tmp_path, "pkg/a.py", NL.join(["import os", "", "def parse(line):",
                                       "    if not line:",
                                       "        raise ValueError('empty')",
                                       "    return line.split()", ""]))
    store = factsguard.Store(tmp_path, cap=1, tickets=1)
    record = factsguard.Record(tmp_path)
    src = 'seq 1 worker.md; evidence: pkg/a.py:5 "raise ValueError"'
    one = {"scope": "pkg/a.py", "kind": "why", "claim": "parse raises",
           "why": "w", "source": src}
    tidy = dict(one, kind="nice-to-do", claim="name the line in the raise")
    assert store.add(factsguard.Proposal(one), record)[0] is not None
    assert store.add(factsguard.Proposal(tidy), record)[0] is not None
    fact, said = store.add(factsguard.Proposal(
        dict(tidy, claim="name the file in the raise")), record)
    assert fact is None and "tickets" in said, said


def test_the_retro_is_told_the_tickets_it_may_write(tmp_path, monkeypatch,
                                                   fake_cli):
    fake = clean(tmp_path, monkeypatch, fake_cli, "## change first\n- none\n")
    assert engine.main() == 0
    prompt = fake.calls[-1]["stdin"].decode("utf-8")
    assert "nice-to-do tickets this run may write:" in prompt
    assert "doc edits and guards this run may make" not in prompt
    assert json.dumps(prompt).count("edit:") == 0
