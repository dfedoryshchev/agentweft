"""the retro, with `retro: true`, runs after every run that ends, is handed
the run's record, and proposes facts, supersessions, re-anchors, retirements,
guards and doc changes in one typed block. the runner holds each to the
record and writes the facts; guards and doc changes are only proposed."""
import json
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import factsguard
from agentweft.orchestrate import facts
from agentweft.runner import engine, retro
from test_stops import CLAUDE, a_flow, answer, steps_of, the_folder

NL = chr(10)
CODE = NL.join(["import os", "", "def parse(line):", "    if not line:",
                "        raise ValueError('empty')", "    return line.split()",
                ""])
REPLAYS = ("worker\ngates:\n  - gate: red-first\n    command: [python, -m,"
           " pytest, '{test}']")


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def asked(fake):
    return [c["stdin"].decode("utf-8") for c in fake.calls]


def block(*items):
    return "## change first\n- none\n\nFACTS\n" + NL.join(items) + "\nEND FACTS\n"


GOOD = NL.join(["fact:", "  scope: pkg/a.py", "  kind: why",
                "  label: important",
                "  claim: parse raises on an empty line, never returns []",
                "  why: the caller counts on the raise for its one error line",
                '  source: seq 1 worker.md; evidence: pkg/a.py:5 "raise'
                ' ValueError"', "  anchor: pkg/a.py:3-6"])
BAD = NL.join(["fact:", "  scope: pkg/gone.py", "  kind: why",
               "  claim: a file that is not there", "  why: made up",
               '  source: seq 1 worker.md; evidence: pkg/a.py:5 "raise'
               ' ValueError"'])
GUARD = NL.join(["guard: seq 1", "  kind: test", "  where: tests/test_a.py",
                 "  what: an empty line raises ValueError"])
DOC = NL.join(["doc: README.md", "  now: parse returns a list",
               "  after: parse returns a list and raises on an empty line",
               "  because: the run found the raise undocumented"])


def clean(tmp_path, monkeypatch, fake_cli, said, steps=("worker",)):
    a_flow(tmp_path, monkeypatch, "keeps", list(steps),
           tail="retro: true\n" + CLAUDE)
    put(tmp_path, "pkg/a.py", CODE)
    return fake_cli(*([answer("done\n")] * len(steps) + [answer(said)]))


def test_a_clean_run_still_calls_the_retro_to_maintain(tmp_path, monkeypatch,
                                                       fake_cli):
    fake = clean(tmp_path, monkeypatch, fake_cli, "## change first\n- none\n")
    assert engine.main() == 0
    assert len(fake.calls) == 2
    prompt = asked(fake)[-1]
    assert "- none failed" in prompt
    assert (the_folder() / "retro.md").is_file()


def test_one_valid_fact_is_written_one_refused_and_a_guard_proposed(
        tmp_path, monkeypatch, fake_cli):
    clean(tmp_path, monkeypatch, fake_cli, block(GOOD, BAD, GUARD, DOC))
    assert engine.main() == 0
    [fact] = facts.read(tmp_path)
    assert fact.id == "F-0001" and fact.status == "live"
    assert fact.get("written").endswith(" by runner from retro")
    assert fact.get("label") == "important"
    assert fact.get("anchor").startswith("pkg/a.py:3-6 sha256:")
    folder = the_folder()
    said = (folder / "retro.md").read_text(encoding="utf-8")
    assert ("- refused a fact on pkg/gone.py: the scope pkg/gone.py is not in"
            " the place") in said
    proposed = (tmp_path / "facts" / "PROPOSED.md").read_text(
        encoding="utf-8")
    assert "kind: test" in proposed and "where: tests/test_a.py" in proposed
    assert "now: parse returns a list" in proposed
    assert "## doc README.md" in proposed
    last = steps_of(folder)[-1]
    assert last["step"] == "retro.md"
    assert last["facts"]["written"] == ["F-0001"]
    assert last["facts"]["refused"] == [
        {"item": "fact on pkg/gone.py",
         "why": "the scope pkg/gone.py is not in the place"}]
    assert last["facts"]["proposed"] == 2
    note = (folder / "handoff.md").read_text(encoding="utf-8")
    part = note.split("## the retro's proposals")[1]
    assert "- wrote F-0001 (pkg/a.py, why): parse raises" in part
    assert "- refused a fact on pkg/gone.py: the scope" in part
    assert "- guard (test, tests/test_a.py): an empty line raises" in part
    assert "- doc README.md: parse returns a list and raises" in part
    index = (tmp_path / "facts" / "INDEX.md").read_text(encoding="utf-8")
    assert "- F-0001 pkg/a.py important: parse raises on an empty line" \
        in index
    assert factsguard.Store(tmp_path).check("next") == ""


def test_a_block_that_does_not_parse_writes_nothing_and_says_so(
        tmp_path, monkeypatch, fake_cli):
    clean(tmp_path, monkeypatch, fake_cli, "FACTS\n" + GOOD + "\n")
    assert engine.main() == 0
    assert not (tmp_path / "facts").exists()
    said = (the_folder() / "retro.md").read_text(encoding="utf-8")
    assert "- the FACTS block did not parse: no END FACTS line, so" \
        " nothing was written" in said


def test_an_item_the_block_cannot_read_writes_nothing(tmp_path, monkeypatch,
                                                      fake_cli):
    clean(tmp_path, monkeypatch, fake_cli,
          block(GOOD, "this line is no item"))
    assert engine.main() == 0
    assert facts.read(tmp_path) == []
    said = (the_folder() / "retro.md").read_text(encoding="utf-8")
    assert ("- the FACTS block did not parse: \"this line is no item\" is"
            " neither an item nor one of its fields, so nothing was written"
            in said)


def test_a_stale_fact_at_the_start_is_in_the_retros_inputs(
        tmp_path, monkeypatch, fake_cli):
    fake = clean(tmp_path, monkeypatch, fake_cli, "## change first\n- none\n")
    at = facts.anchored(tmp_path, "pkg/a.py", 3, 6)
    put(tmp_path, "facts/pkg/a.py.md",
        "## F-0001 live\nscope: pkg/a.py\nkind: why\nclaim: parse raises\n"
        "why: the caller\nanchor: " + str(at) + "\n")
    put(tmp_path, "pkg/a.py", CODE.replace("ValueError", "KeyError"))
    engine.main()
    prompt = asked(fake)[-1]
    assert "facts marked stale, to re-anchor, retire or supersede:" in prompt
    assert "- F-0001 pkg/a.py: parse raises (stale: " in prompt


def test_the_record_hands_the_retro_handoff_lines_and_the_issue(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "keeps", [REPLAYS],
           tail="retro: true\n" + CLAUDE)
    said = ("done\n\nHANDOFF\nDID:\n- pkg/a.py: raise on empty\nTRIED:\n"
            "- a print, dropped: stderr took two lines\nDOUBTS:\n"
            "- reader.py may print too\nEND HANDOFF\n")
    fake = fake_cli(answer(said), answer("## change first\n- none\n"))
    engine.main()
    prompt = asked(fake)[-1]
    assert "what each step handed over, from steps.jsonl:" in prompt
    assert "- seq 1 worker.md did: pkg/a.py: raise on empty" in prompt
    assert "- seq 1 worker.md tried: a print, dropped" in prompt
    assert "- seq 1 worker.md doubts: reader.py may print too" in prompt
    assert ("- seq 1 worker.md: red-first could not replay: the place is not"
            " in a git work tree") in prompt
    assert "rulings written in this run, from decisions.md:" in prompt


def test_a_ruling_answered_in_this_leg_reaches_the_retro(tmp_path,
                                                        monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "asks", ["worker"],
           tail="retro: true\nlead: none\n" + CLAUDE)
    fake_cli(answer("NEEDS: which file?\nOPTIONS:\n- a.py\n- b.py\n"))
    engine.main()
    first = the_folder()
    again = fake_cli(answer("done in a.py\n"),
                     answer("## change first\n- none\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "asks", "--force", "--resume",
                                      first.name, "--answer", "a.py"])
    assert engine.main() == 0
    prompt = asked(again)[-1]
    part = prompt.split("rulings written in this run, from decisions.md:")[1]
    assert "- decisions.md " in part.split("\n\n")[0]
    assert "(answer)" in part.split("\n\n")[0]


def test_a_retire_and_a_re_anchor_are_done_by_the_runner(tmp_path,
                                                        monkeypatch, fake_cli):
    at = None
    put(tmp_path, "pkg/a.py", CODE)
    at = facts.anchored(tmp_path, "pkg/a.py", 3, 6)
    put(tmp_path, "facts/pkg/a.py.md",
        "## F-0001 live\nscope: pkg/a.py\nkind: why\nclaim: parse raises\n"
        "why: the caller\nanchor: " + str(at) + "\n\n"
        "## F-0002 live\nscope: pkg/a.py\nkind: why\nclaim: old\nwhy: gone\n")
    put(tmp_path, "pkg/a.py", CODE.replace("ValueError", "KeyError"))
    moved = NL.join(["re-anchor: F-0001", "  anchor: pkg/a.py:3-6",
                     '  evidence: pkg/a.py:5 "raise KeyError"'])
    gone = NL.join(["retire: F-0002", "  why: parse no longer has that path"])
    clean(tmp_path, monkeypatch, fake_cli, block(moved, gone))
    put(tmp_path, "pkg/a.py", CODE.replace("ValueError", "KeyError"))
    engine.main()
    found = dict((f.id, f) for f in facts.read(tmp_path))
    assert found["F-0001"].status == "live"
    assert found["F-0001"].get("anchor") == str(facts.anchored(
        tmp_path, "pkg/a.py", 3, 6))
    assert found["F-0002"].status == "retired"
    assert found["F-0002"].get("retired").endswith(
        "by the retro: parse no longer has that path")


def test_a_re_anchor_whose_evidence_does_not_hold_is_refused(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "pkg/a.py", CODE)
    put(tmp_path, "facts/pkg/a.py.md",
        "## F-0001 stale\nscope: pkg/a.py\nkind: why\nclaim: parse raises\n"
        "why: the caller\nanchor: pkg/a.py:3-6 sha256:" + "0" * 64 + "\n")
    moved = NL.join(["re-anchor: F-0001", "  anchor: pkg/a.py:3-6",
                     '  evidence: pkg/a.py:5 "raise nothing"'])
    clean(tmp_path, monkeypatch, fake_cli, block(moved))
    engine.main()
    [fact] = facts.read(tmp_path)
    assert fact.status == "stale"
    said = (the_folder() / "retro.md").read_text(encoding="utf-8")
    assert ('- refused a re-anchor of F-0001: the evidence does not hold:'
            ' "raise nothing" is not at pkg/a.py:5') in said


def test_a_gate_issue_seen_again_climbs_the_ladder(tmp_path):
    put(tmp_path, "pkg/a.py", CODE)
    item = {"scope": ["pkg/"], "kind": "gate-issue", "label": "none",
            "claim": "the suite times out on pkg at 60 seconds",
            "why": "the gate could not finish in this run",
            "source": 'seq 1 worker.md; evidence: pkg/a.py:5 "raise'
                      ' ValueError"'}
    said = []
    for run in range(4):
        store = factsguard.Store(tmp_path)
        record = factsguard.Record(tmp_path)
        done = retro.Maintained()
        retro.execute(store, record, [("fact", "", dict(item))], done,
                      "run-" + str(run))
        said.append(done)
    [fact] = facts.read(tmp_path)
    assert fact.get("seen").startswith("proposed 4,")
    assert fact.get("label") == "important"
    proposed = (tmp_path / "facts" / "PROPOSED.md").read_text(
        encoding="utf-8")
    assert proposed.count("recurring: ") == 1
    assert "recurring: " + fact.id + " seen in 3 runs" in proposed
    assert said[3].owed == [fact.id + " seen in 4 runs (gate-issue on pkg/):"
                            " the suite times out on pkg at 60 seconds"]
    assert said[1].owed == []


def test_one_run_counts_a_fact_once_however_often_it_is_proposed(tmp_path):
    put(tmp_path, "pkg/a.py", CODE)
    item = {"scope": ["pkg/a.py"], "kind": "why", "claim": "one claim",
            "why": "a why", "source": 'seq 1 w.md; evidence: pkg/a.py:5'
                                      ' "raise ValueError"'}
    store = factsguard.Store(tmp_path)
    record = factsguard.Record(tmp_path)
    done = retro.Maintained()
    retro.execute(store, record, [("fact", "", dict(item))] * 3, done, "r")
    [fact] = facts.read(tmp_path)
    assert fact.get("seen").startswith("proposed 1,")


def test_facts_per_run_is_a_count(tmp_path):
    from agentweft.flow import spec

    base = {"name": "f", "steps": [{"role": "worker"}]}
    assert spec.check(dict(base, facts_per_run=1)) == []
    assert spec.check(dict(base, facts_per_run="lots")) == [
        "facts_per_run should be a whole number, 0 or more"]


def test_the_flows_cap_holds_the_retros_new_facts(tmp_path, monkeypatch,
                                                  fake_cli):
    second = GOOD.replace("never returns []", "and says which line")
    a_flow(tmp_path, monkeypatch, "keeps", ["worker"],
           tail="retro: true\nfacts_per_run: 1\n" + CLAUDE)
    put(tmp_path, "pkg/a.py", CODE)
    fake_cli(answer("done\n"), answer(block(GOOD, second)))
    engine.main()
    assert [f.id for f in facts.read(tmp_path)] == ["F-0001"]
    said = (the_folder() / "retro.md").read_text(encoding="utf-8")
    assert "per-run cap: 1 new facts are already written this run" in said
    data = json.loads((the_folder() / "facts.json").read_text(
        encoding="utf-8"))
    assert [w["id"] for w in data["written"]][:1] == ["F-0001"]
