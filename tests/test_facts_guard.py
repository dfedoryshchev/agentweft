"""only the runner writes the project's facts.

a step's Write and Edit tools are refused under facts/, a step that changes
the store anyway fails like a gate and the store is put back, and a fact the
runner is asked to write is held to the record first: its scope is in the
place, its evidence is there, its anchor is hashed by the runner, it carries
no secret, and a run writes at most a few new ones."""
import json
import sys

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.guardrails import shellwrite
from agentweft.orchestrate import facts
from agentweft.runner import stops

try:
    from agentweft.guardrails import factsguard
except ImportError:
    factsguard = None

import test_spec_files as sf

NL = chr(10)
CODE = NL.join(["import os", "", "def parse(line):", "    if not line:",
                "        raise ValueError('empty')", "    return line.split()",
                ""])


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def entry(id, scope, claim):
    return ("## " + id + " live" + NL + "scope: " + scope + NL
            + "kind: convention" + NL + "claim: " + claim + NL
            + "why: the spec says so" + NL)


def proposal(**given):
    fields = {"scope": ["pkg/a.py"], "kind": "why", "label": "none",
              "claim": "parse raises on an empty line, never returns []",
              "why": "the caller counts on the raise for its one error line",
              "source": 'seq 2 worker.md; evidence: pkg/a.py:5 "raise'
                        ' ValueError"',
              "anchor": "pkg/a.py:3-6"}
    fields.update(given)
    return factsguard.Proposal(fields)


def a_store(tmp_path, cap=3, ran=(), stamps=()):
    put(tmp_path, "pkg/a.py", CODE)
    store = factsguard.Store(tmp_path, cap=cap)
    return store, factsguard.Record(tmp_path, ran=ran, stamps=stamps)


def test_a_step_that_edits_a_fact_fails_like_a_gate_and_it_is_put_back(
        tmp_path, monkeypatch):
    place = sf.a_place(tmp_path / "repo")
    before = entry("F-0001", "report.py", "report keeps the given order")
    put(place, "facts/report.py.md", before)
    sf.git(place, "add", ".")
    sf.git(place, "commit", "-qm", "facts")
    sf.flow_with(tmp_path, "additions")
    does = sf.worker_writes(sf.SPEC)
    writes, said = does["worker.md"]
    does["worker.md"] = (dict(writes, **{"facts/report.py.md": before.replace(
        "keeps the given order", "may sort")}), said)
    code, called = sf.running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.GATE)
    assert called == ["tester.md", "worker.md", "worker.md"]
    gates = sf.read(sf.folders()[-1] / "gates.md")
    assert "facts/report.py.md was changed by worker.md" in gates
    assert "facts come only from the runner" in gates
    assert (place / "facts" / "report.py.md").read_text(
        encoding="utf-8") == before


def test_a_step_that_adds_a_facts_file_fails_and_it_is_taken_away(tmp_path):
    store = factsguard.Store(tmp_path)
    put(tmp_path, "facts/pkg/_folder.md", entry("F-0001", "pkg/", "made up"))
    said = store.check("worker.md")
    assert "facts/pkg/_folder.md was changed by worker.md" in said
    assert "added or edited F-0001" in said
    assert not (tmp_path / "facts" / "pkg" / "_folder.md").exists()
    assert store.check("worker.md") == ""


def test_a_proposal_with_a_token_shaped_string_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    fact, why = store.add(proposal(claim="the deploy reads " + token),
                          record)
    assert fact is None
    assert why == "it looks like a secret: a token in claim"
    assert token not in why
    assert facts.read(tmp_path) == []


def test_a_proposal_naming_a_credential_file_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(why="the keys are in .env, read at"
                                       " start"), record)
    assert fact is None
    assert why == "it looks like a secret: a credential file in why"


def test_a_long_mixed_string_is_refused_and_a_hash_is_not(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(
        claim="the key is Zq8vT2mX9pL4rW7nB3kY6hJ1sD5fG0aQ"), record)
    assert why == "it looks like a secret: a long random string in claim"
    fact, why = store.add(proposal(claim="the start was c5aa5960d460d126ed02"
                                         "e3169f463c2fac0b9d11d90833e83fef42f4"
                                         "a698b733"), record)
    assert why == "" and fact is not None


def test_a_proposal_whose_quote_is_not_at_that_line_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(
        source='seq 2 worker.md; evidence: pkg/a.py:2 "raise ValueError"'),
        record)
    assert fact is None
    assert why == ('the evidence does not hold: "raise ValueError" is not at'
                   " pkg/a.py:2")


def test_a_proposal_with_no_evidence_the_runner_can_check_is_refused(
        tmp_path):
    store, record = a_store(tmp_path)
    for source in ("seq 2 worker.md", "seq 2 worker.md; evidence: it is so"):
        fact, why = store.add(proposal(source=source), record)
        assert fact is None
        assert why.startswith("the evidence does not hold"), why


def test_command_and_ruling_evidence_hold_only_when_on_record(tmp_path):
    store, record = a_store(tmp_path, cap=9,
                            ran=[("python -m pytest -q", 1)],
                            stamps=["2026-10-19 14:31"])
    ok, why = store.add(proposal(
        source="seq 3 worker.md; evidence: python -m pytest -q exit 1"),
        record)
    assert why == ""
    _, why = store.add(proposal(
        claim="a second one",
        source="seq 3 worker.md; evidence: python -m pytest -q exit 0"),
        record)
    assert why == ("the evidence does not hold: no gate in this run ran"
                   " `python -m pytest -q` to exit 0")
    _, why = store.add(proposal(
        claim="a third one",
        source="seq 3 worker.md; evidence: decisions.md 2026-10-19 14:31"),
        record)
    assert why == ""
    _, why = store.add(proposal(
        claim="a fourth one",
        source="seq 3 worker.md; evidence: decisions.md 2026-10-19 09:00"),
        record)
    assert why == ("the evidence does not hold: no ruling on record in"
                   " decisions.md at 2026-10-19 09:00")


def test_the_runner_hashes_the_anchor_itself(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(anchor="pkg/a.py:3-6 sha256:" + "0" * 64),
                          record)
    assert why == ""
    want = facts.anchored(tmp_path, "pkg/a.py", 3, 6)
    assert fact.get("anchor") == str(want)
    _, why = store.add(proposal(claim="past the end", anchor="pkg/a.py:3-90"),
                       record)
    assert why == "the anchor pkg/a.py:3-90 is not lines of the file"


def test_a_scope_that_is_not_in_the_place_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    _, why = store.add(proposal(scope=["pkg/b.py"], anchor=""), record)
    assert why == "the scope pkg/b.py is not in the place"


def test_a_claim_with_no_why_or_two_lines_or_a_pipe_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    assert store.add(proposal(why=""), record)[1] == "it has no why"
    assert store.add(proposal(claim="one\ntwo"), record)[1] == \
        "the claim is more than one line"
    assert store.add(proposal(claim="a | b"), record)[1] == \
        "claim holds a |, which no taught format carries"


def test_a_hand_written_entry_present_at_the_start_counts(tmp_path):
    put(tmp_path, "facts/pkg/_folder.md", entry("F-0001", "pkg/", "by hand"))
    store = factsguard.Store(tmp_path)
    assert [f.id for f in store.read()] == ["F-0001"]
    store.keep_in(tmp_path / "run")
    data = json.loads((tmp_path / "run" / "facts.json").read_text(
        encoding="utf-8"))
    assert len(data["found"]) == 1 and data["written"] == []


def test_the_fourth_new_fact_in_one_run_is_refused_for_the_cap(tmp_path):
    store, record = a_store(tmp_path)
    for n in range(3):
        fact, why = store.add(proposal(claim="fact number " + str(n)), record)
        assert why == "" and fact.id == "F-000" + str(n + 1)
    fact, why = store.add(proposal(claim="fact number 3"), record)
    assert fact is None
    assert why == "per-run cap: 3 new facts are already written this run"
    assert len(facts.read(tmp_path)) == 3


def test_the_same_claim_again_counts_on_the_live_fact(tmp_path):
    store, record = a_store(tmp_path)
    first, _ = store.add(proposal(), record)
    again, why = store.add(proposal(claim="Parse raises on an empty line,"
                                          " never returns [] "), record)
    assert why == ""
    assert again.id == first.id
    [fact] = facts.read(tmp_path)
    assert fact.get("seen") == ("proposed 2, attached 0, honoured 0,"
                                " contradicted 0")
    assert store.new == 1


def test_a_written_fact_carries_its_source_and_who_wrote_it(tmp_path):
    store, record = a_store(tmp_path)
    store.keep_in(tmp_path / "run")
    fact, _ = store.add(proposal(), record, today="2026-10-22 08:00")
    [read] = facts.read(tmp_path)
    assert read.file == tmp_path / "facts" / "pkg" / "a.py.md"
    assert read.get("source").endswith('evidence: pkg/a.py:5 "raise'
                                       ' ValueError"')
    assert read.get("written") == "2026-10-22 08:00 by runner"
    data = json.loads((tmp_path / "run" / "facts.json").read_text(
        encoding="utf-8"))
    assert [w["id"] for w in data["written"]] == [fact.id]
    assert store.check("retro.md") == ""


def test_a_supersession_keeps_the_old_fact_marked(tmp_path):
    store, record = a_store(tmp_path)
    old, _ = store.add(proposal(), record)
    new, why = store.add(proposal(claim="parse raises KeyError now",
                                  supersedes=old.id), record)
    assert why == ""
    found = dict((f.id, f) for f in facts.read(tmp_path))
    assert found[old.id].status == "superseded"
    assert found[new.id].get("supersedes") == old.id
    _, why = store.add(proposal(claim="x", supersedes="F-0099"), record)
    assert why == "it supersedes F-0099, which is not a live or stale fact"


def test_the_hook_refuses_a_write_under_the_facts_folder(tmp_path):
    keep = str(tmp_path / "facts") + "/"

    def hook(tool, given):
        data = {"tool_name": tool, "tool_input": given, "cwd": str(tmp_path),
                "session_id": "s"}
        return shellwrite.decide([str(tmp_path / "denials.jsonl"), "--keep",
                                  keep], json.dumps(data))

    code, said = hook("Write", {"file_path": str(tmp_path / "facts" / "pkg"
                                                 / "a.py.md"), "content": "x"})
    assert code == 2
    assert "facts" in said and "only the runner" in said
    assert hook("Edit", {"file_path": "facts/_project.md"})[0] == 2
    assert hook("Write", {"file_path": str(tmp_path / "factsheet.md"),
                          "content": "x"}) == (0, "")


def test_a_step_granted_write_has_the_facts_folder_kept(tmp_path):
    p = providers.build({"provider": "cli", "command": "claude"},
                        where=tmp_path, grant=["read", "write"])
    argv, _ = p.argv("hi")
    settings = json.loads(argv[argv.index("--settings") + 1])
    args = settings["hooks"]["PreToolUse"][0]["hooks"][0]["args"]
    kept = [args[i + 1] for i, a in enumerate(args) if a == "--keep"]
    assert (tmp_path.resolve() / "facts").as_posix() + "/" in kept
