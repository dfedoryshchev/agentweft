"""a stopped run's handoff ends with the command that carries it on, a cap
given on the command line holds until it is raised, a finished run asks for
nothing it was already answered, and the trail keeps the order the steps ran.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions, park
from agentweft.runner import engine, prompts, stops, summary

NL = chr(10)
NEEDS = ("NEEDS: keep the old name or the new one?" + NL + "OPTIONS:" + NL
         + "- old" + NL + "- new" + NL)
DECIDED = "DECIDED: old" + NL + "why: the readme uses the old name" + NL


def a_flow(tmp_path, monkeypatch, name, steps, tail=""):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + NL + tail + "steps:" + NL
    for role, extra in steps:
        body = body + "  - role: " + role + NL + "    prompt: " + role + ".md" + NL
        for line in extra:
            body = body + "    " + line + NL
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])


def answering(monkeypatch, said=None):
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        n = asked.count(step)
        asked.append(step)
        got = (said or {}).get(step)
        if got:
            return got[min(n, len(got) - 1)], False
        return "done by " + step + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run.py"] + list(argv))
    return engine.main()


def folders(tmp_path):
    return sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())


def handoff(folder):
    return (folder / summary.FILE).read_text(encoding="utf-8") \
        .rstrip(NL).split(NL)


THREE = [("a", []), ("b", []), ("c", [])]


def test_a_cap_given_on_the_command_line_holds_on_a_plain_resume(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "given", THREE)
    asked = answering(monkeypatch)
    assert run(monkeypatch, "given", "--force", "--max-calls", "2") == \
        stops.EXIT_STOP
    [first] = folders(tmp_path)
    asked[:] = []
    capsys.readouterr()
    assert run(monkeypatch, "given", "--force", "--resume", first.name) == 1
    assert asked == []
    assert "--max-calls" in capsys.readouterr().out
    assert folders(tmp_path) == [first]


def test_a_budget_park_ends_on_the_raised_cap_form(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "raise", THREE)
    answering(monkeypatch)
    run(monkeypatch, "raise", "--force", "--max-calls", "2")
    [first] = folders(tmp_path)
    assert handoff(first)[-1] == ("  python run.py raise --resume "
                                  + first.name + " --force --max-calls <n>")


def test_a_kept_cap_is_repeated_and_raising_it_is_a_ruling_on_record(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "kept",
           [("a", []), ("b", ["pause: user"]), ("c", [])])
    asked = answering(monkeypatch)
    run(monkeypatch, "kept", "--force", "--max-calls", "2")
    [first] = folders(tmp_path)
    assert handoff(first)[-1] == ("  python run.py kept --resume "
                                  + first.name + " --force --max-calls 2")
    asked[:] = []
    assert run(monkeypatch, "kept", "--force", "--resume", first.name) == 1
    assert asked == []
    assert run(monkeypatch, "kept", "--force", "--resume", first.name,
               "--max-calls", "3") == stops.EXIT_OK
    assert asked == ["c.md"]
    [said] = decisions.read(tmp_path)
    assert "call cap from 2 to 3" in said.decided
    [second] = [p for p in folders(tmp_path) if p != first]
    note = NL.join(handoff(second))
    assert "none on record in decisions.md" not in note
    assert "call cap from 2 to 3" in note


def test_a_ruling_park_ends_on_the_answer_form(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "asks", [("a", []), ("b", [])])
    answering(monkeypatch, {"a.md": [NEEDS]})
    run(monkeypatch, "asks", "--force")
    [first] = folders(tmp_path)
    assert handoff(first)[-1] == ("  python run.py asks --resume "
                                  + first.name + " --force" + park.ANSWER)


def test_a_conflict_ends_on_both_answer_forms():
    command = "python run.py f --resume f-1"
    needs = park.lines("a.md", None, [], ["a.md"], command,
                       question="NEEDS: which holds?", conflict=True)
    lines = summary.build("f-1", "f", None, [], {"git": False}, [], "",
                          stopped={"cause": stops.CONFLICT, "why": "x",
                                   "at": "a.md"},
                          needs=needs, command=command)
    assert lines[-2:] == ["  " + command + park.OVERRIDE,
                          "  " + command + park.REQUEST]


def test_a_declined_run_ends_saying_it_ended_with_no_resume_line(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "says-no", [("a", []), ("b", [])])
    (tmp_path / "SPEC.md").write_text("no renames" + NL, encoding="utf-8")
    answering(monkeypatch, {"a.md": ['REFUSED: SPEC.md:1 "no renames"' + NL]})
    assert run(monkeypatch, "says-no", "--force") == stops.EXIT_OK
    [first] = folders(tmp_path)
    lines = handoff(first)
    tail = lines[lines.index("## run"):]
    assert not any("--resume" in l for l in tail)
    assert "ended" in tail[-1]


def test_a_finished_run_does_not_ask_what_an_answer_settled(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "answered", [("a", []), ("b", [])])
    answering(monkeypatch, {"a.md": [NEEDS, "renamed" + NL]})
    run(monkeypatch, "answered", "--force")
    [first] = folders(tmp_path)
    capsys.readouterr()
    assert run(monkeypatch, "answered", "--force", "--resume", first.name,
               "--answer", "old") == stops.EXIT_OK
    [second] = [p for p in folders(tmp_path) if p != first]
    note = handoff(second)
    assert "## needs you" not in note
    assert any(l.startswith("- on record: ") and "ruling for a.md: old" in l
               for l in note)
    assert "keep the old name" not in capsys.readouterr().out


def lead_run(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "led", [("planner", []), ("worker", [])],
           tail="lead: planner" + NL)
    answering(monkeypatch, {"planner.md": ["- rename it" + NL, DECIDED],
                            "worker.md": [NEEDS, "renamed" + NL]})
    assert run(monkeypatch, "led", "--force") == stops.EXIT_OK
    [folder] = folders(tmp_path)
    return folder


def test_a_question_the_lead_decided_is_not_left_open(tmp_path, monkeypatch,
                                                      capsys):
    folder = lead_run(tmp_path, monkeypatch)
    note = handoff(folder)
    assert "## needs you" not in note
    assert any("planner.md decided for worker.md: old" in l for l in note)
    assert "keep the old name" not in capsys.readouterr().out


def test_the_asking_pass_is_written_before_the_leads(tmp_path, monkeypatch):
    folder = lead_run(tmp_path, monkeypatch)
    lines = [json.loads(l) for l in (folder / "steps.jsonl")
             .read_text(encoding="utf-8").split(NL) if l.strip()]
    assert [(l["seq"], l["step"], l["outcome"]) for l in lines] == [
        (1, "planner.md", "ok"), (2, "worker.md", "asked"),
        (3, "planner.md", "decided"), (4, "worker.md", "ok")]
    ran = [l for l in handoff(folder) if l.startswith("led ran ")]
    assert ran[0].startswith(
        "led ran planner.md -> worker.md -> planner.md -> worker.md in ")
