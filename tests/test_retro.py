"""`retro: true` adds one last step that reads why each failed attempt failed
and writes runs/<id>/retro.md. it is advice: it never fails or stops a run."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.roles import resolver
from agentweft.runner import chain, engine, manifest, state
from agentweft.runner import retro
from test_stops import (CLAUDE, a_flow, answer, ends, refused_by_the_limit,
                        steps_of, the_folder)

GATED = "worker\ngates:\n  - gate: length\n    max_lines: 1"


def two_fails(tmp_path, monkeypatch, fake_cli, tail="", last=None):
    """a worker whose length gate fails twice, the second time for good."""
    a_flow(tmp_path, monkeypatch, "fails", [GATED, "reviewer"],
           tail=tail + CLAUDE)
    retro = [last if last is not None else answer("## seq 1 worker.md\n")]
    return fake_cli(answer("one\ntwo\n"), answer("one\ntwo\nthree\n"), *retro)


def asked(fake):
    return [c["stdin"].decode("utf-8") for c in fake.calls]


def test_a_retro_is_handed_why_each_failed_attempt_failed(
        tmp_path, monkeypatch, fake_cli):
    fake = two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n")
    assert engine.main() == 2
    prompts = asked(fake)
    assert len(prompts) == 3
    prompt = prompts[-1]
    whys = [l["why"] for l in steps_of(the_folder()) if l["why"]]
    assert len(whys) == 2 and whys[0] != whys[1]
    assert "- seq 1 worker.md, gate failed: " + whys[0] in prompt
    assert "- seq 2 worker.md, gate failed: " + whys[1] in prompt
    assert resolver.skill("retro") in prompt
    assert resolver.role_prompt("retro.md") in prompt


def test_a_retro_writes_retro_md_and_its_cost_like_a_step(
        tmp_path, monkeypatch, fake_cli):
    two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n")
    engine.main()
    folder = the_folder()
    assert (folder / "retro.md").read_text(encoding="utf-8") == \
        "## seq 1 worker.md\n"
    last = steps_of(folder)[-1]
    assert (last["step"], last["outcome"], last["won"]) == \
        ("retro.md", "ok", "none")
    assert last["cost"] == 0.25
    assert last["budget"] is None
    assert manifest.load(folder).spend["calls"] == 3


@pytest.mark.parametrize("tail", ["", "retro: false\n"],
                         ids=["absent", "off"])
def test_retro_off_or_absent_adds_no_step(tail, tmp_path, monkeypatch,
                                          fake_cli):
    fake = two_fails(tmp_path, monkeypatch, fake_cli, tail=tail)
    assert engine.main() == 2
    assert len(fake.calls) == 2
    folder = the_folder()
    assert [l["step"] for l in steps_of(folder)] == ["worker.md"] * 2
    assert not (folder / "retro.md").exists()


def test_a_retro_that_errors_leaves_the_outcome_as_it_was(
        tmp_path, monkeypatch, fake_cli):
    two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n",
              last=(RuntimeError("the cli fell over"), b"", b""))
    assert engine.main() == 2
    folder = the_folder()
    [end] = ends()
    assert (end.status, end.cause) == ("failed at worker.md", "gate failed")
    assert manifest.load(folder).data["outcome"] == "stopped: gate failed"
    last = steps_of(folder)[-1]
    assert (last["step"], last["outcome"]) == ("retro.md", "failed")
    assert "the cli fell over" in last["why"]
    assert not (folder / "retro.md").exists()


def test_a_run_with_no_failed_attempt_hands_the_retro_none_to_look_at(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "clean", ["worker", "reviewer"],
           tail="retro: true\n" + CLAUDE)
    fake = fake_cli(answer("done\n"), answer("VERDICT: ok\n\nfine\n"),
                    answer("## change first\n- none\n"))
    assert engine.main() == 0
    assert len(fake.calls) == 3
    assert "failed, from steps.jsonl:\n- none failed\n" in asked(fake)[-1]
    assert (the_folder() / "retro.md").exists()


def test_a_retro_skill_is_not_fed_to_every_role():
    assert resolver.skill("retro")
    assert resolver.skill("retro") not in resolver.skill_rules()
    assert resolver.skill("retro") in resolver.skill_rules("retro")
    assert resolver.skill("no-guessing") in resolver.skill_rules("retro")


def test_the_retro_is_taught_to_keep_an_open_question_and_a_pinning_test():
    skill = " ".join(resolver.skill("retro").split())
    assert ("an open question two or more steps raised, that no ruling"
            " settled, is a `why` fact labelled `investigation`") in skill
    assert ("a test a step said passes on the code before the change as well"
            " pins what the code does and does not prove the change: a `why`"
            " fact labelled `investigation`") in skill


@pytest.mark.parametrize("scope, claim, evidence", [
    ("pkg/parse.py", "whether a time outside the years 0001 to 9999 is valid is"
     " open: parse accepts it", 'TASK.md:2 "a time is YYYY-MM-DD"'),
    ("tests/test_parse.py", "test_edge passes on the code before the change"
     " too: it pins the output, it does not prove the fix",
     'tests/test_parse.py:1 "def test_edge():"')])
def test_an_investigation_fact_of_the_taught_shape_is_written(
        tmp_path, scope, claim, evidence):
    from agentweft.guardrails import factsguard

    for rel, text in (("TASK.md", "# spec\na time is YYYY-MM-DD\n"),
                      ("pkg/parse.py", "def parse(line):\n    return line\n"),
                      ("tests/test_parse.py", "def test_edge():\n    pass\n")):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8", newline="\n")
    store = factsguard.Store(tmp_path)
    fact, why = store.add(factsguard.Proposal({
        "scope": [scope], "kind": "why", "label": "investigation",
        "claim": claim, "why": "two steps raised it and no ruling settled it",
        "source": "seq 3 reviewer.md; evidence: " + evidence}),
        factsguard.Record(tmp_path))
    assert why == "" and fact is not None
    assert (fact.get("kind"), fact.get("label")) == ("why", "investigation")


def test_retro_on_a_flow_is_true_false_or_conditional():
    from agentweft.flow import spec

    bad = spec.check({"name": "f", "steps": [{"role": "worker"}],
                      "retro": "yes please"})
    assert bad == ["retro should be true, false or conditional"]
    assert spec.check({"name": "f", "steps": [{"role": "worker"}],
                       "retro": True}) == []


def test_a_send_back_hands_the_retro_the_reviewers_reason(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "sent", ["worker", "reviewer"],
           tail="retro: true\n" + CLAUDE)
    fake = fake_cli(answer("done\n"),
                    answer("VERDICT: redo\n\nthe file is not named\n"),
                    answer("done in a.py\n"), answer("VERDICT: ok\n\nfine\n"),
                    answer("## change first\n"))
    assert engine.main() == 0
    assert "- seq 2 reviewer.md, redo: the file is not named\n" \
        in asked(fake)[-1]


def test_a_resume_counts_the_retro_and_owes_it_no_handoff_block(
        tmp_path, monkeypatch, fake_cli):
    two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n")
    engine.main()
    first = the_folder()
    assert chain.verify(first).broken is None
    fake_cli(answer("one\n"), answer("VERDICT: ok\n\nfine\n"),
             answer("## change first\n- none\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "fails", "--force",
                                      "--resume", first.name])
    assert engine.main() == 0
    [again] = [p for p in state.RUNS.iterdir() if p.is_dir() and p != first]
    note = (again / "handoff.md").read_text(encoding="utf-8")
    assert "- retro.md 0s ($0.2500), won none, checked 0: no events" in note
    assert "handoff missing: retro.md" not in note
    assert "handoff missing: worker.md" in note


def test_a_retro_that_cannot_write_its_record_leaves_the_outcome(
        tmp_path, monkeypatch, fake_cli):
    from agentweft.runner import trace

    two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n")
    real = trace.Trail.open

    def full(self, step, *a, **kw):
        if step == "retro.md":
            raise OSError("no space left on device")
        return real(self, step, *a, **kw)

    monkeypatch.setattr(trace.Trail, "open", full)
    assert engine.main() == 2
    [end] = ends()
    assert (end.status, end.cause) == ("failed at worker.md", "gate failed")
    assert manifest.load(the_folder()).data["outcome"] == \
        "stopped: gate failed"


LOOKED = "why each failed attempt failed"


def outcomes(folder):
    return [l["step"] + ":" + l["outcome"] for l in steps_of(folder)]


def test_the_retro_is_fenced_like_the_flows_own_steps(tmp_path, monkeypatch,
                                                      fake_cli):
    gated = "worker\ntools: [read]\ngates:\n  - gate: length\n    max_lines: 1"
    a_flow(tmp_path, monkeypatch, "fenced", [gated, "reviewer\ntools: [read]"],
           tail="retro: true\n" + CLAUDE)
    fake = fake_cli(answer("one\ntwo\n"), answer("one\ntwo\nthree\n"),
                    answer("## seq 1 worker.md\n"))
    engine.main()
    assert len(fake.calls) == 3
    assert "--tools" in fake.calls[0]["argv"]
    assert "--tools" in fake.calls[-1]["argv"], fake.calls[-1]["argv"]


def test_the_retro_only_reads_even_when_no_step_is_fenced(
        tmp_path, monkeypatch, fake_cli):
    fake = two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n")
    engine.main()
    from agentweft.providers import cli_provider

    argv = fake.calls[-1]["argv"]
    assert "--tools" not in fake.calls[0]["argv"]
    fenced = cli_provider.fence(retro.GRANT)
    at = argv.index("--tools")
    assert argv[at:at + len(fenced)] == fenced
    assert "--restricted" in fenced


def test_a_run_waiting_for_a_ruling_holds_its_retro(tmp_path, monkeypatch,
                                                    fake_cli):
    a_flow(tmp_path, monkeypatch, "asks", ["worker", "reviewer"],
           tail="retro: true\nlead: none\n" + CLAUDE)
    fake = fake_cli(answer("NEEDS: which file?\nOPTIONS:\n- a.py\n- b.py\n"))
    engine.main()
    assert outcomes(the_folder()) == ["worker.md:parked"]
    assert len(fake.calls) == 1


def test_failures_before_a_budget_stop_reach_the_retro_of_the_leg_that_ends(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "capped", ["worker", "reviewer"],
           tail="retro: true\nmax_calls: 3\n" + CLAUDE)
    first = fake_cli(answer("done\n"),
                     answer("VERDICT: redo\n\nthe file is not named\n"),
                     answer("done in a.py\n"))
    engine.main()
    leg = the_folder()
    assert outcomes(leg)[-1] == "reviewer.md:parked"
    assert not any(LOOKED in p for p in asked(first))
    again = fake_cli(answer("VERDICT: ok\n\nfine\n"), answer("## change first\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "capped", "--force", "--resume",
                                      leg.name, "--max-calls", "10"])
    assert engine.main() == 0
    [prompt] = [p for p in asked(again) if LOOKED in p]
    assert "- seq 2 reviewer.md, redo: the file is not named\n" in prompt
    assert "parked" not in prompt.split(LOOKED)[1].split("\n\n")[0]


def test_a_failure_one_retro_looked_at_is_not_handed_to_the_next(
        tmp_path, monkeypatch, fake_cli):
    two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n")
    engine.main()
    first = the_folder()
    again = fake_cli(answer("one\n"), answer("VERDICT: ok\n\nfine\n"),
                     answer("## change first\n- none\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "fails", "--force",
                                      "--resume", first.name])
    assert engine.main() == 0
    assert len(again.calls) == 3
    prompt = asked(again)[-1]
    assert "failed, from steps.jsonl:\n- none failed\n" in prompt
    assert "gate failed: " not in prompt.split("why.md:")[0]


@pytest.mark.parametrize("step", ["role: retro", "role: worker\n    prompt: retro.md"])
def test_a_flow_cannot_name_a_step_retro(step):
    from agentweft.flow import spec
    import yaml

    raw = yaml.safe_load("name: f\nsteps:\n  - " + step + "\n")
    assert any("retro" in b and "look-back" in b for b in spec.check(raw)), \
        spec.check(raw)


def test_a_run_at_its_call_cap_spends_nothing_on_a_retro(
        tmp_path, monkeypatch, fake_cli):
    fake = two_fails(tmp_path, monkeypatch, fake_cli,
                     tail="retro: true\nmax_calls: 2\n")
    engine.main()
    assert len(fake.calls) == 2
    assert outcomes(the_folder())[-1] == "worker.md:gate failed"


def test_passes_that_did_what_they_were_asked_are_not_failed_attempts():
    lines = [{"seq": n, "step": "worker.md", "outcome": o, "why": "w",
              "to": to}
             for n, (o, to) in enumerate([("ok", None), ("asked", "lead.md"),
                                          ("decided", None),
                                          ("escalated", None),
                                          ("redo", "investigator.md"),
                                          ("redo", "worker.md")], 1)]
    assert [l["seq"] for l in retro.failed(lines)] == [6]


def test_a_retro_that_comes_back_empty_is_a_failed_line(
        tmp_path, monkeypatch, fake_cli):
    two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n",
              last=answer(""))
    assert engine.main() == 2
    last = steps_of(the_folder())[-1]
    assert (last["step"], last["outcome"]) == ("retro.md", "failed")
    assert "nothing came out of retro.md" in last["why"]
    assert not (the_folder() / "retro.md").exists()


def section(note, heading):
    return note.split("## " + heading + "\n", 1)[1].split("\n## ", 1)[0]


def test_the_handoff_s_spend_lines_count_the_retro_that_ran_after_it(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "clean", ["worker", "reviewer"],
           tail="retro: true\n" + CLAUDE)
    fake_cli(answer("done\n"), answer("VERDICT: ok\n\nfine\n"),
             answer("## change first\n- none\n"))
    assert engine.main() == 0
    note = (the_folder() / "handoff.md").read_text(encoding="utf-8")
    spent = section(note, "retro")
    assert spent.split("\n")[:5] == [
        "- worker.md 0.0s ($0.2500), won none, checked 0: no events",
        "- reviewer.md 0.0s ($0.2500), won none, checked 0: no events",
        "- retro.md 0.0s ($0.2500), won none, checked 0: no events (after this"
        " handoff was written)",
        "- won none: 3 passes, 0s, $0.7500",
        "- USD on steps that won nothing and checked nothing: $0.5000 of"
        " $0.7500"]
    assert "- upkeep, not waste: the retro $0.2500" in spent.split("\n")
    assert "- total: 3 passes, 0s, $0.7500" in spent.split("\n")
    run = section(note, "run")
    assert "- spend: 3 calls, " in run and ", the retro's call included" \
        in run, run


def test_a_retro_the_limit_refused_is_still_charged(
        tmp_path, monkeypatch, fake_cli):
    two_fails(tmp_path, monkeypatch, fake_cli, tail="retro: true\n",
              last=refused_by_the_limit())
    assert engine.main() == 2
    folder = the_folder()
    assert outcomes(folder)[-1] == "retro.md:failed"
    assert manifest.load(folder).spend["refused_calls"] == 1
