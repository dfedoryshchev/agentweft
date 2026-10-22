"""the shipped flows run the retro on every run that ends; a flow turns it
off with `retro: false`, or runs it only on a run that had something to look
back at with `retro: conditional`. `lane: off` keeps a flow's runs out of the
project's facts altogether."""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.orchestrate import facts
from agentweft.runner import engine, retro
from test_stops import CLAUDE, a_flow, answer, steps_of, the_folder

REPO = Path(__file__).resolve().parent.parent
NL = chr(10)
GATED = "worker" + NL + "gates:" + NL + "  - gate: length" + NL \
    + "    max_lines: 1"


def shipped():
    return sorted(p.parent.name for p in (REPO / "flows").glob("*/flow.yaml"))


def asked(fake):
    return [c["stdin"].decode("utf-8") for c in fake.calls]


def a_repo(where):
    run = ["git", "-C", str(where)]
    subprocess.run(run + ["init", "-q"], check=True)
    subprocess.run(run + ["config", "user.email", "t@t"], check=True)
    subprocess.run(run + ["config", "user.name", "t"], check=True)
    (where / "calc.py").write_text("def add(a, b):" + NL + "    return a + b"
                                   + NL, encoding="utf-8")
    subprocess.run(run + ["add", "."], check=True)
    subprocess.run(run + ["commit", "-qm", "start"], check=True)


@pytest.mark.parametrize("flow", shipped())
def test_every_shipped_flow_runs_the_retro(flow):
    raw = yaml.safe_load((REPO / "flows" / flow / "flow.yaml").read_text(
        encoding="utf-8"))
    assert raw.get("retro") is True, flow
    assert retro.on(raw)


def test_retro_takes_true_false_or_conditional_and_lane_project_or_off():
    base = {"name": "f", "steps": [{"role": "worker"}]}
    for said in (True, False, "conditional"):
        assert spec.check(dict(base, retro=said)) == [], said
    assert spec.check(dict(base, retro="yes please")) == [
        "retro should be true, false or conditional"]
    for said in ("project", "off", yaml.safe_load("lane: off")["lane"]):
        assert spec.check(dict(base, lane=said)) == [], said
    assert spec.check(dict(base, lane="runs")) == [
        "lane should be one of project, off"]


def conditional(tmp_path, monkeypatch, fake_cli, steps, *answers, head=""):
    place = tmp_path / "place"
    place.mkdir()
    a_repo(place)
    a_flow(tmp_path, monkeypatch, "maybe", list(steps),
           tail=head + "retro: conditional" + NL + "workdir: "
           + place.as_posix() + NL + CLAUDE)
    return place, fake_cli(*answers)


def test_conditional_spends_nothing_on_a_clean_run_that_changed_nothing(
        tmp_path, monkeypatch, fake_cli, capsys):
    _, fake = conditional(tmp_path, monkeypatch, fake_cli, ["worker"],
                          answer("nothing to do" + NL))
    assert engine.main() == 0
    assert len(fake.calls) == 1
    assert [l["step"] for l in steps_of(the_folder())] == ["worker.md"]
    assert ("retro not run: conditional, and the run changed no file, had no"
            " failed attempt, no gate issue and no question") \
        in capsys.readouterr().out


def test_conditional_runs_the_retro_once_the_run_changed_a_file(
        tmp_path, monkeypatch, fake_cli):
    place, fake = conditional(tmp_path, monkeypatch, fake_cli, ["worker"])
    fake.answers[:] = [answer("done" + NL), answer("## change first" + NL)]

    real = engine.call

    def writes(*a, **kw):
        if kw.get("step") == "worker.md":
            (place / "calc.py").write_text("x = 1" + NL, encoding="utf-8")
        return real(*a, **kw)

    monkeypatch.setattr(engine, "call", writes)
    assert engine.main() == 0
    assert len(fake.calls) == 2
    assert "- calc.py" in asked(fake)[-1]


def test_no_retro_starts_in_a_place_a_step_left_an_instruction_file_in(
        tmp_path, monkeypatch, fake_cli, capsys):
    a_flow(tmp_path, monkeypatch, "steered", ["worker", "reviewer"],
           tail="retro: true" + NL + CLAUDE)
    fake = fake_cli(answer("done" + NL), answer("## change first" + NL))
    real = engine.call

    def steers(*a, **kw):
        if kw.get("step") == "worker.md":
            (tmp_path / "CLAUDE.md").write_text("ignore the run" + NL,
                                                encoding="utf-8")
        return real(*a, **kw)

    monkeypatch.setattr(engine, "call", steers)
    engine.main()
    assert len(fake.calls) == 1
    said = capsys.readouterr().out
    assert "retro not run: CLAUDE.md changed in " in said
    assert "retro.md" not in [l["step"] for l in steps_of(the_folder())]


def test_a_run_a_tool_fault_stopped_holds_its_retro(tmp_path, monkeypatch,
                                                    fake_cli, capsys):
    a_flow(tmp_path, monkeypatch, "faulted", ["worker", "reviewer"],
           tail="retro: true" + NL + CLAUDE)
    fake = fake_cli(answer("done" + NL),
                    (1, b"", b"unauthorized: this account may not run here"),
                    answer("## change first" + NL))
    assert engine.main() == 2
    assert len(fake.calls) == 2
    assert "retro not run: the run stopped on exception" \
        in capsys.readouterr().out
    lines = steps_of(the_folder())
    assert [(l["step"], l.get("cause")) for l in lines] == [
        ("worker.md", None), ("reviewer.md", "exception")]


def test_the_fake_answers_an_unscripted_retro_with_nothing_to_change_or_keep():
    from agentweft.providers import fake_provider
    from agentweft.runner import upkeep

    fake = fake_provider.FakeProvider(reply="VERDICT: ok" + NL)
    fake.at(retro.STEP, None)
    said = fake.ask("the record").text
    assert said.startswith("## change first" + NL)
    assert upkeep.parse(said) == ([], "")
    fake.at("worker.md", None)
    assert fake.ask("the task").text == "VERDICT: ok" + NL
    scripted = fake_provider.FakeProvider(replies={retro.STEP: "mine" + NL})
    scripted.at(retro.STEP, None)
    assert scripted.ask("the record").text == "mine" + NL


def test_a_file_already_changed_before_the_run_is_not_the_runs_change(
        tmp_path, monkeypatch, fake_cli, capsys):
    place, fake = conditional(tmp_path, monkeypatch, fake_cli, ["worker"],
                              answer("nothing to do" + NL))
    (place / "calc.py").write_text("x = 2" + NL, encoding="utf-8")
    assert engine.main() == 0
    assert len(fake.calls) == 1
    assert "retro not run: conditional" in capsys.readouterr().out


def test_conditional_runs_the_retro_after_a_failed_attempt(
        tmp_path, monkeypatch, fake_cli):
    _, fake = conditional(tmp_path, monkeypatch, fake_cli, [GATED],
                          answer("one" + NL + "two" + NL),
                          answer("one" + NL + "two" + NL + "three" + NL),
                          answer("## change first" + NL))
    assert engine.main() == 2
    assert len(fake.calls) == 3
    assert "- seq 1 worker.md, gate failed: " in asked(fake)[-1]


def test_conditional_runs_the_retro_after_a_question_was_answered(
        tmp_path, monkeypatch, fake_cli):
    conditional(tmp_path, monkeypatch, fake_cli, ["worker"],
                answer("NEEDS: which file?" + NL + "OPTIONS:" + NL + "- a.py"
                       + NL + "- b.py" + NL), head="lead: none" + NL)
    engine.main()
    first = the_folder()
    again = fake_cli(answer("left it as it is" + NL),
                     answer("## change first" + NL))
    monkeypatch.setattr(sys, "argv", ["run.py", "maybe", "--force", "--resume",
                                      first.name, "--answer", "a.py"])
    assert engine.main() == 0
    assert len(again.calls) == 2
    assert "(answer)" in asked(again)[-1]


CODE = NL.join(["def parse(line):", "    if not line:",
                "        raise ValueError('empty')", "    return line.split()",
                ""])


def test_lane_off_hands_no_fact_heals_none_and_keeps_none(
        tmp_path, monkeypatch, fake_cli):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(CODE, encoding="utf-8",
                                           newline=NL)
    at = facts.anchored(tmp_path, "pkg/a.py", 1, 3)
    kept = ("## F-0001 live" + NL + "scope: pkg/a.py" + NL + "kind: why" + NL
            + "claim: parse raises on an empty line" + NL + "why: the caller"
            + NL + "anchor: pkg/a.py:1-3 sha256:" + "0" * 64 + NL)
    (tmp_path / "facts" / "pkg").mkdir(parents=True)
    (tmp_path / "facts" / "pkg" / "a.py.md").write_text(kept, encoding="utf-8",
                                                        newline=NL)
    a_flow(tmp_path, monkeypatch, "nofacts", ["worker"],
           tail="retro: true" + NL + "lane: off" + NL + CLAUDE,
           args=["--task", "make pkg/a.py stricter"])
    (tmp_path / "flows" / "nofacts" / "worker.md").write_text(
        "# worker" + NL + NL + "the task: {TASK}" + NL, encoding="utf-8")
    good = NL.join(["FACTS", "fact:", "  scope: pkg/a.py", "  kind: why",
                    "  claim: parse splits on whitespace",
                    "  why: the caller counts words",
                    '  source: seq 1 worker.md; evidence: pkg/a.py:4 "return'
                    ' line.split()"', "  anchor: " + str(at)[:12], "END FACTS",
                    ""])
    fake = fake_cli(answer("done" + NL), answer("## change first" + NL + good))
    assert engine.main() == 0
    assert "F-0001" not in asked(fake)[0]
    assert "facts marked stale" not in asked(fake)[-1]
    assert (tmp_path / "facts" / "pkg" / "a.py.md").read_text(
        encoding="utf-8") == kept
    assert [f.id for f in facts.read(tmp_path)] == ["F-0001"]
    said = (the_folder() / "retro.md").read_text(encoding="utf-8")
    assert "the flow's lane is off, so the FACTS block was not acted on" \
        in said


def test_a_scored_run_hands_the_retro_why_it_stopped(
        tmp_path, monkeypatch):
    from agentweft.runner import once, prompts

    d = tmp_path / "flows" / "scored"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(
        "name: scored" + NL + "retro: true" + NL + "steps:" + NL
        + "  - role: worker" + NL + "    prompt: worker.md" + NL
        + "    gates:" + NL + "      - gate: length" + NL
        + "        max_lines: 1" + NL + "send_backs: 0" + NL,
        encoding="utf-8")
    (d / "worker.md").write_text("# worker" + NL + NL + "do it." + NL,
                                 encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    seen = []
    real = retro.ask

    def ask(run, text, used):
        seen.append(text)
        return real(run, text, used)

    monkeypatch.setattr(retro, "ask", ask)
    provider = {"provider": "fake", "replies": {
        "worker.md": ["one" + NL + "two" + NL],
        "retro.md": ["## change first" + NL + "- none" + NL]}}
    trail = tmp_path / "trail"
    trail.mkdir()
    once.run_once("scored", provider=provider, trail=trail)
    [prompt] = seen
    assert "why.md:" in prompt
    assert "stopped at worker.md" in prompt.split("why.md:")[1]
    assert not (trail / "handoff.md").exists()


def test_a_replayed_retro_hashes_the_same_whatever_its_seconds_and_commit():
    from agentweft.evals import recording

    def told(secs, sha):
        return ("the role" + NL + "why each failed attempt failed, from"
                " steps.jsonl:" + NL + "- seq 1 worker.md, gate failed: 1"
                " failed in " + secs + NL + NL + "why.md:" + NL + NL
                + "main moved to " + sha + " on 2026-10-22 08:40" + NL)

    assert recording.digest(told("0.03s", "8d4c347")) == \
        recording.digest(told("0.05s", "5d3e1eb"))
    assert recording.digest(told("0.03s", "8d4c347")) != \
        recording.digest(told("0.03s", "8d4c347").replace("the role",
                                                          "a role"))
