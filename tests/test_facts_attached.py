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


def test_a_place_with_no_facts_gets_the_brief_it_got_before(tmp_path):
    notes = brief.Brief(tmp_path, ["planner.md", "worker.md"])
    assert notes.text("planner.md") == ""
    assert notes.text("planner.md", handed=[]) == ""
    assert notes.key("planner.md") == notes.key("planner.md", handed=[])
