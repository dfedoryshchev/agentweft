"""a step handed a file is handed what the project's facts say about it: the
first step from the files the task names and the spec, every later step from
those and the files the steps before it read, ruled on or did. each fact comes
with its why and its source, its anchored lines quoted, the stale ones marked,
and the ids handed go on the step's line in steps.jsonl."""
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import facts
from agentweft.runner import brief, engine
from test_stops import CLAUDE, a_flow, answer, steps_of, the_folder

NL = chr(10)
CODE = NL.join(["import sys", "", "def parse(line):", "    if not line:",
                "        raise ParseError('empty')", "    return line.split()",
                ""])
CLI = NL.join(["from . import parse", "", "def main(argv):",
               "    return parse.parse(argv[0])", ""])


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def entry(id, scope, claim, why, status="live", anchor="", label=""):
    lines = ["## " + id + " " + status, "scope: " + scope, "kind: convention"]
    if label:
        lines.append("label: " + label)
    lines.extend(["claim: " + claim, "why: " + why,
                  "source: run r-1 step worker.md seq 2; evidence: TASK.md:1"
                  ' "errors"'])
    if anchor:
        lines.append("anchor: " + anchor)
    return NL.join(lines) + NL


def a_place(tmp_path):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "pkg/cli.py", CLI)
    put(tmp_path, "TASK.md", "# task" + NL + NL + "errors are raised." + NL)
    at = facts.anchored(tmp_path, "pkg/parse.py", 3, 5)
    put(tmp_path, "facts/pkg/parse.py.md",
        entry("F-0001", "pkg/parse.py", "parse raises ParseError, never prints",
              "the one-line stderr rule broke when parse printed",
              anchor=str(at), label="important"))
    put(tmp_path, "facts/pkg/_folder.md",
        entry("F-0002", "pkg/", "every module under pkg/ raises, cli.py prints",
              "one error line on stderr, said once"))
    return at


def asked(fake):
    return [c["stdin"].decode("utf-8") for c in fake.calls]


def a_run(tmp_path, monkeypatch, fake_cli, steps, *answers, task=None,
          head=""):
    a_flow(tmp_path, monkeypatch, "facts", list(steps), tail=head + CLAUDE,
           args=["--task", task] if task else ())
    if task:
        first = steps[0].split(NL)[0]
        (tmp_path / "flows" / "facts" / (first + ".md")).write_text(
            "# " + first + NL + NL + "the task: {TASK}" + NL, encoding="utf-8")
    return fake_cli(*answers)


def read_line(rel):
    return ("done" + NL + NL + "HANDOFF" + NL + "DID:" + NL + "- planned it"
            + NL + "READ:" + NL + "- " + rel + " - where main is" + NL
            + "END HANDOFF" + NL)


def test_a_planner_whose_task_names_a_file_gets_its_facts_with_their_why(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter")
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert "facts for the files you are handed" in prompt
    assert "F-0001 pkg/parse.py" in prompt
    assert "parse raises ParseError, never prints" in prompt
    assert "why: the one-line stderr rule broke when parse printed" in prompt
    assert "source: run r-1 step worker.md seq 2" in prompt
    assert "3: def parse(line):" in prompt
    assert prompt.index("F-0001") < prompt.index("F-0002")
    [line] = steps_of(the_folder())
    assert line["facts_attached"] == ["F-0001", "F-0002"]


def test_a_later_step_gets_the_folder_facts_of_a_file_read_before_it(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner", "worker"],
                 answer(read_line("pkg/cli.py:3-4")), answer("done" + NL))
    assert engine.main() == 0
    first, second = asked(fake)
    assert "F-0002" not in first
    assert "every module under pkg/ raises, cli.py prints" in second
    assert "F-0001" not in second
    lines = steps_of(the_folder())
    assert "facts_attached" not in lines[0]
    assert lines[1]["facts_attached"] == ["F-0002"]
    [kept] = [f for f in facts.read(tmp_path) if f.id == "F-0002"]
    assert "attached 1" in kept.get("seen")


def test_a_windows_path_in_the_task_finds_the_same_facts(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg\\parse.py stricter")
    assert engine.main() == 0
    assert "F-0001 pkg/parse.py" in asked(fake)[0]


def test_a_stale_fact_is_handed_marked_after_the_live_ones(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    put(tmp_path, "pkg/parse.py", CODE.replace("ParseError", "ValueError"))
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter")
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert "F-0001 pkg/parse.py (convention, important), possibly stale" \
        in prompt
    assert "lines changed since it was anchored" in prompt
    assert prompt.index("F-0002") < prompt.index("F-0001")


def test_a_step_with_the_brief_off_is_handed_no_facts(tmp_path, monkeypatch,
                                                      fake_cli):
    a_place(tmp_path)
    fake = a_run(tmp_path, monkeypatch, fake_cli, ["planner"],
                 answer("done" + NL), task="make pkg/parse.py stricter",
                 head="brief: false" + NL)
    assert engine.main() == 0
    [prompt] = asked(fake)
    assert "F-0001" not in prompt and "F-0002" not in prompt
    assert "facts_attached" not in steps_of(the_folder())[0]


def test_past_the_facts_cap_the_rest_are_named_by_id_and_file(tmp_path):
    a_place(tmp_path)
    long = "x" * 300
    put(tmp_path, "facts/pkg/cli.py.md", NL.join(
        entry("F-%04d" % n, "pkg/cli.py", "rule %d " % n + long, "why " + long)
        for n in range(3, 13)))
    notes = brief.Brief(tmp_path, ["planner.md"])
    handed = facts.lookup(tmp_path, "pkg/cli.py")
    text = notes.text("planner.md", handed=handed)
    part = text.split("facts for the files you are handed")[1]
    assert len(part) <= brief.FACTS_CAP + 400
    assert "left out at the size cap" in text
    assert "F-0012 (facts/pkg/cli.py.md)" in text


def test_the_runners_own_writes_are_not_a_change_to_the_product(tmp_path):
    from agentweft.guardrails import snapshot

    a_place(tmp_path)
    start = snapshot.take(tmp_path)
    put(tmp_path, "facts/pkg/parse.py.md", "## F-0001 live" + NL)
    put(tmp_path, "facts/INDEX.md", "# facts" + NL)
    put(tmp_path, "decisions.md", "## 2026-10-22 09:00  a ruling" + NL)
    assert start.product_changed() == []
    put(tmp_path, "pkg/cli.py", CLI + "# more" + NL)
    assert start.product_changed() == ["pkg/cli.py"]
    start.product["facts/pkg/_folder.md"] = "0" * 64
    start.save(tmp_path / ".kept")
    assert snapshot.load(tmp_path / ".kept").product_changed() == [
        "pkg/cli.py"]


def test_a_resumed_leg_does_not_take_the_runners_counts_for_the_work(
        tmp_path, monkeypatch, fake_cli):
    a_place(tmp_path)
    asks = answer("NEEDS: which file?" + NL + "OPTIONS:" + NL + "- a.py" + NL
                  + "- b.py" + NL)
    a_run(tmp_path, monkeypatch, fake_cli,
          ["worker\ngates:\n  - gate: red-first\n    command: [python, -m,"
           " pytest, '{test}']"], asks, task="make pkg/parse.py stricter",
          head="lead: none\n")
    engine.main()
    first = the_folder()
    assert "attached 1" in (tmp_path / "facts" / "pkg" / "parse.py.md"
                            ).read_text(encoding="utf-8")
    fake_cli(asks)
    monkeypatch.setattr(sys, "argv", ["run.py", "facts", "--force", "--resume",
                                      first.name, "--answer", "a.py"])
    engine.main()
    [*_, last] = sorted((p for p in first.parent.iterdir() if p.is_dir()
                         and (p / "handoff.md").is_file()),
                        key=lambda p: p.name)
    page = (last / "handoff.md").read_text(encoding="utf-8")
    assert "asked for a ruling instead of doing the work" in page, page
    assert "the place holds its change to" not in page


def a_fact(id, kind, label, claim):
    lines = ["## " + id + " live", "scope: pkg/parse.py", "kind: " + kind]
    if label:
        lines.append("label: " + label)
    lines.extend(["claim: " + claim, "why: a run showed it"])
    _, [fact] = facts.parse(NL.join(lines) + NL)
    return fact


KINDS_HANDED = [
    a_fact("F-0001", "decision", "important", "parse raises, never prints"),
    a_fact("F-0002", "why", "investigation",
           "whether a blank line is an error is open"),
    a_fact("F-0003", "why", "pins", "test_blank passes without the change"),
    a_fact("F-0004", "defect", "", "parse drops a trailing tab"),
    a_fact("F-0005", "convention", "", "errors are raised as ParseError"),
    a_fact("F-0006", "gate-issue", "", "the suite times out on pkg"),
]


def headed(lines):
    """-> {header line: [the fact ids under it]} of a facts section."""
    out, now = {}, None
    for line in lines:
        if line.startswith("- F-"):
            out[now].append(line.split(" ")[1])
        elif line and not line.startswith(" "):
            now = line
            out[now] = []
    return out


def test_an_open_question_and_a_pin_are_handed_as_open_never_as_rules(
        tmp_path):
    notes = brief.Brief(tmp_path, ["planner.md"])
    said = headed(notes.kept_facts(KINDS_HANDED))
    assert said == {brief.FACTS_HEAD: ["F-0001", "F-0005"],
                    brief.OPEN_HEAD: ["F-0002", "F-0003"],
                    brief.TROUBLE_HEAD: ["F-0004", "F-0006"]}
    assert "hold to them" in brief.FACTS_HEAD
    for head in (brief.OPEN_HEAD, brief.TROUBLE_HEAD):
        assert "hold to them" not in head and "not a rule" in head


def test_with_only_open_facts_nothing_says_hold_to_them(tmp_path):
    notes = brief.Brief(tmp_path, ["planner.md"])
    text = "\n".join(notes.kept_facts(KINDS_HANDED[1:3]))
    assert "hold to them" not in text
    assert text.startswith(brief.OPEN_HEAD)


def test_a_files_own_facts_come_before_its_folders_and_the_projects(
        tmp_path):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "facts/_project.md", entry(
        "F-0001", ".", "the project raises, never prints", "said once",
        label="important"))
    put(tmp_path, "facts/pkg/_folder.md", entry(
        "F-0002", "pkg/", "pkg raises ParseError", "said once",
        label="important"))
    put(tmp_path, "facts/pkg/parse.py.md", entry(
        "F-0003", "pkg/parse.py", "parse splits on whitespace", "said once")
        + NL + entry("F-0004", "pkg/parse.py", "parse keeps tabs", "said once",
                     status="stale"))
    order = [f.id for f in facts.handed(tmp_path, ["pkg/parse.py"])]
    assert order == ["F-0003", "F-0002", "F-0001", "F-0004"]


def test_the_projects_facts_are_handed_two_at_most_and_the_rest_named(
        tmp_path):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "facts/_project.md", NL.join(
        entry("F-%04d" % n, ".", "project rule %d" % n, "said once")
        for n in range(1, 5)))
    handed = facts.handed(tmp_path, ["pkg/parse.py"])
    notes = brief.Brief(tmp_path, ["planner.md"])
    shown, _, project = notes.fit(handed)
    assert [f.id for f, _ in shown] == ["F-0001", "F-0002"]
    assert [f.id for f in project] == ["F-0003", "F-0004"]
    text = "\n".join(notes.kept_facts(handed))
    assert ("2 more project-wide facts left out; open them yourself if you"
            " need them: F-0003 (facts/_project.md), F-0004"
            " (facts/_project.md)") in text


def test_a_ninth_live_project_wide_fact_is_refused(tmp_path):
    from agentweft.guardrails import factsguard

    put(tmp_path, "TASK.md", "# task" + NL + NL + "errors are raised." + NL)
    put(tmp_path, "pkg/parse.py", CODE)
    store, record = factsguard.Store(tmp_path, cap=20), \
        factsguard.Record(tmp_path)

    def one(scope, n):
        return factsguard.Proposal({
            "scope": [scope], "kind": "why", "claim": "claim %d" % n,
            "why": "a why", "source": 'seq 1 w.md; evidence: TASK.md:3'
            ' "errors are raised."'})

    for n in range(facts.PROJECT_CAP):
        assert store.add(one(".", n), record)[1] == ""
    for scope in (".", "**", "./**"):
        fact, why = store.add(one(scope, 99), record)
        assert fact is None, scope
        assert why.startswith("the project already has 8 live project-wide"
                              " facts"), scope
    assert store.add(one("pkg/parse.py", 99), record)[1] == ""
    assert store.add(one("**/*.py", 98), record)[1] == ""


def test_a_glob_over_every_file_is_project_wide_and_held_to_the_cap(tmp_path):
    put(tmp_path, "pkg/parse.py", CODE)
    put(tmp_path, "facts/_project.md", NL.join(
        entry("F-%04d" % n, scope, "project rule %d" % n, "said once")
        for n, scope in ((1, "."), (2, "**"), (3, "**"))))
    shown, _, project = brief.Brief(tmp_path, ["planner.md"]).fit(
        facts.handed(tmp_path, ["pkg/parse.py"]))
    assert [f.id for f, _ in shown] == ["F-0002", "F-0003"]
    assert [f.id for f in project] == ["F-0001"]


def test_a_place_with_no_facts_gets_the_brief_it_got_before(tmp_path):
    notes = brief.Brief(tmp_path, ["planner.md", "worker.md"])
    assert notes.text("planner.md") == ""
    assert notes.text("planner.md", handed=[]) == ""
    assert notes.key("planner.md") == notes.key("planner.md", handed=[])
