"""which model each role runs on, chosen for one run without touching the flow."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.runner import cli, engine, models

from test_trace import CLAUDE, FAKE, a_flow, answer, every_line, folders, \
    lines, no_waiting


def argv_models(calls):
    """-> the --model each call was started with, None for none."""
    out = []
    for c in calls:
        argv = c["argv"]
        out.append(argv[argv.index("--model") + 1] if "--model" in argv
                   else None)
    return out


@pytest.fixture
def tiers(monkeypatch):
    for key in ("MODEL", "MODEL_HIGH", "MODEL_MID", "MODEL_LOW"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MODEL_HIGH", "big-id")
    monkeypatch.setenv("MODEL_LOW", "small-id")


# parsing what was typed


def test_one_flag_can_carry_several_roles():
    assert models.parse(["planner=opus,reviewer=low"]) == \
        {"planner": "opus", "reviewer": "low"}


def test_the_flag_given_twice_adds_up():
    assert models.parse(["planner=opus", "reviewer = low "]) == \
        {"planner": "opus", "reviewer": "low"}


@pytest.mark.parametrize("typed,said", [
    ("reviewer=", "reviewer has no model"),
    ("reviewer", "reviewer is not role=model"),
    ("=low", "=low has no role"),
    ("planner=opus,planner=haiku", "planner is given twice"),
])
def test_a_pair_that_says_nothing_usable_is_refused(typed, said):
    with pytest.raises(ValueError) as e:
        models.parse([typed])
    assert said in str(e.value)


def test_a_role_the_flow_does_not_have_is_refused_with_the_ones_it_does():
    flow = spec.load({"name": "x", "steps": [{"role": "worker"},
                                             {"role": "reviewer"},
                                             {"role": "reviewer",
                                              "prompt": "second.md"}]})
    assert models.unknown({"revewer": "low"}, flow) == (
        "no role called revewer in x. there is: worker, reviewer")
    assert models.unknown({"reviewer": "low"}, flow) == ""


def test_the_seam_effort_will_use_takes_any_flag_name():
    assert models.pairs(["--effort-for", "reviewer=high"], "--effort-for") == \
        ["reviewer=high"]
    assert models.pairs(["run.py", "x"], "--model-for") == []
    with pytest.raises(ValueError) as e:
        models.pairs(["run.py", "x", "--model-for"], "--model-for")
    assert "--model-for needs role=model" in str(e.value)


# the flow file's own key


def test_the_flow_file_may_name_a_tier_per_role():
    assert spec.check({"name": "x", "steps": [{"role": "reviewer"}],
                       "tiers": {"reviewer": "low"}}) == []


@pytest.mark.parametrize("tiers_key,said", [
    ({"revewer": "low"}, "tiers: no role called revewer. there is: reviewer"),
    ({"reviewer": "opus"}, "tiers: reviewer should be one of high, mid, low"),
    ({"reviewer": ""}, "tiers: reviewer should be one of high, mid, low"),
    (["reviewer"], "tiers should be a mapping of role to tier"),
])
def test_a_flow_file_tiers_key_is_checked_like_a_step_model(tiers_key, said):
    bad = spec.check({"name": "x", "steps": [{"role": "reviewer"}],
                      "tiers": tiers_key})
    assert bad == [said]


# what a run sends and records


def test_the_flag_sends_one_role_its_model_and_leaves_the_rest(
        tmp_path, monkeypatch, fake_cli, tiers):
    a_flow(tmp_path, monkeypatch, "two", ["worker", "reviewer"],
           args=["--model-for", "reviewer=low"])
    cli_ = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nfine\n"))
    assert engine.main() == 0
    assert argv_models(cli_.calls) == ["m-small", "small-id"]
    worker, reviewer = lines(folders(tmp_path)[0])
    assert worker["model"] == "m-small" and worker["model_choice"] is None
    assert reviewer["model"] == "small-id"
    assert reviewer["model_choice"] == {"role": "reviewer", "asked": "low",
                                        "from": "run", "applies": True}
    assert reviewer["model_reported"] == "m-small-1"


def test_a_model_id_goes_through_as_it_was_typed(tmp_path, monkeypatch,
                                                 fake_cli, tiers):
    a_flow(tmp_path, monkeypatch, "named", ["worker", "reviewer"],
           args=["--model-for", "worker=opus,reviewer=sonnet"])
    cli_ = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nfine\n"))
    engine.main()
    assert argv_models(cli_.calls) == ["opus", "sonnet"]
    assert [l["model_choice"]["asked"] for l in every_line(tmp_path)] == \
        ["opus", "sonnet"]


def test_an_unknown_role_is_refused_before_anything_is_asked(
        tmp_path, monkeypatch, fake_cli, capsys):
    a_flow(tmp_path, monkeypatch, "typo", ["worker", "reviewer"],
           args=["--model-for", "revewer=low"])
    cli_ = fake_cli(answer("should not be asked\n"))
    assert engine.main() == 1
    assert cli_.calls == []
    assert "no role called revewer in typo. there is: worker, reviewer" in \
        capsys.readouterr().out
    assert not (tmp_path / "runs").exists()


def test_an_empty_model_is_refused_before_anything_is_asked(
        tmp_path, monkeypatch, fake_cli, capsys):
    a_flow(tmp_path, monkeypatch, "blank", ["worker", "reviewer"],
           args=["--model-for", "reviewer="])
    cli_ = fake_cli(answer("should not be asked\n"))
    assert engine.main() == 1
    assert cli_.calls == []
    assert "reviewer has no model" in capsys.readouterr().out


def test_a_role_run_twice_gets_the_model_at_both_steps(
        tmp_path, monkeypatch, fake_cli, tiers):
    a_flow(tmp_path, monkeypatch, "pair", ["worker"],
           args=["--model-for", "reviewer=high"])
    folder = tmp_path / "flows" / "pair"
    (folder / "flow.yaml").write_text(
        "name: pair\nsteps:\n  - role: worker\n    prompt: worker.md\n"
        "  - role: reviewer\n    prompt: cut.md\n"
        "  - role: reviewer\n    prompt: grow.md\n" + CLAUDE, encoding="utf-8")
    for name in ("cut.md", "grow.md"):
        (folder / name).write_text("# reviewer\n", encoding="utf-8")
    cli_ = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nfine\n"),
                    answer("VERDICT: ok\n\nfine\n"))
    engine.main()
    assert argv_models(cli_.calls) == ["m-small", "big-id", "big-id"]
    assert [(l["step"], l["model"]) for l in every_line(tmp_path)] == [
        ("worker.md", "m-small"), ("cut.md", "big-id"), ("grow.md", "big-id")]


def test_every_fanned_out_task_runs_on_the_role_model(
        tmp_path, monkeypatch, fake_cli, tiers):
    a_flow(tmp_path, monkeypatch, "wide",
           ["planner", "worker\nfanout: true\nworkers: 2", "merge"],
           args=["--model-for", "worker=low"])
    cli_ = fake_cli(answer("TASK: look at a\nFILES:\n- a.py\n\nTASK: look at b\nFILES:\n- b.py\n"))
    engine.main()
    assert argv_models(cli_.calls) == ["m-small", "small-id", "small-id",
                                       "m-small"]
    fan = every_line(tmp_path)[1]
    assert fan["model"] == "small-id"
    assert fan["model_choice"]["asked"] == "low"
    assert [t["model_reported"] for t in fan["tasks"]] == ["m-small-1"] * 2


def test_a_command_that_is_not_claude_records_the_choice_as_not_applied(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "other", ["worker"],
           tail="provider:\n  provider: cli\n  command: mycli\n",
           args=["--model-for", "worker=opus"])
    cli_ = fake_cli((0, b"did it\n", b""))
    engine.main()
    assert cli_.calls[0]["argv"][:2] == ["mycli", "-p"]
    assert "--model" not in cli_.calls[0]["argv"]
    [line] = every_line(tmp_path)
    assert line["model"] is None
    assert line["model_choice"] == {"role": "worker", "asked": "opus",
                                    "from": "run", "applies": False}


def test_a_provider_with_no_models_records_the_choice_as_not_applied(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "canned", ["worker"], tail=FAKE,
           args=["--model-for", "worker=low"])
    engine.main()
    [line] = every_line(tmp_path)
    assert line["provider"] == "fake"
    assert line["model_choice"]["applies"] is False


# precedence: the run, the step, the flow, the environment


def test_the_run_beats_the_step(tmp_path, monkeypatch, fake_cli, tiers):
    a_flow(tmp_path, monkeypatch, "over", ["worker\nmodel: high"],
           args=["--model-for", "worker=low"])
    cli_ = fake_cli(answer("did it\n"))
    engine.main()
    assert argv_models(cli_.calls) == ["small-id"]
    assert every_line(tmp_path)[0]["model_choice"]["from"] == "run"


def test_a_run_tier_beats_the_model_the_provider_block_names(
        tmp_path, monkeypatch, fake_cli, tiers):
    """a tier from the step loses to `provider: {model: ...}`, which has
    already answered the question. the run's own choice was made after that
    answer, for this run, and losing to it would make the flag do nothing on
    any flow that names a model."""
    a_flow(tmp_path, monkeypatch, "block", ["worker"],
           args=["--model-for", "worker=high"])
    cli_ = fake_cli(answer("did it\n"))
    engine.main()
    assert argv_models(cli_.calls) == ["big-id"]


def test_the_step_beats_the_flow(tmp_path, monkeypatch, fake_cli, tiers):
    a_flow(tmp_path, monkeypatch, "layered", ["worker\nmodel: high"],
           tail="tiers:\n  worker: low\nprovider:\n  provider: cli\n")
    cli_ = fake_cli(answer("did it\n"))
    engine.main()
    assert argv_models(cli_.calls) == ["big-id"]
    assert every_line(tmp_path)[0]["model_choice"] == {
        "role": "worker", "asked": "high", "from": "step", "applies": True}


def test_the_flow_beats_the_environment(tmp_path, monkeypatch, fake_cli,
                                        tiers):
    monkeypatch.setenv("MODEL", "the-only-one")
    a_flow(tmp_path, monkeypatch, "flowkey", ["worker", "reviewer"],
           tail="tiers:\n  reviewer: low\nprovider:\n  provider: cli\n")
    cli_ = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nfine\n"))
    engine.main()
    assert argv_models(cli_.calls) == ["the-only-one", "small-id"]
    worker, reviewer = every_line(tmp_path)
    assert worker["model_choice"] is None
    assert reviewer["model_choice"]["from"] == "flow"


def test_the_environment_answers_when_nothing_chose(tmp_path, monkeypatch,
                                                     fake_cli, tiers):
    monkeypatch.setenv("MODEL", "the-only-one")
    a_flow(tmp_path, monkeypatch, "plain", ["worker"],
           tail="provider:\n  provider: cli\n")
    cli_ = fake_cli(answer("did it\n"))
    engine.main()
    assert argv_models(cli_.calls) == ["the-only-one"]
    assert every_line(tmp_path)[0]["model_choice"] is None


# a resumed run


def test_a_resumed_run_keeps_the_model_map_it_started_with(
        tmp_path, monkeypatch, fake_cli, tiers):
    a_flow(tmp_path, monkeypatch, "kept", ["worker", "reviewer"],
           args=["--model-for", "reviewer=low"])
    no_waiting(monkeypatch)
    fake_cli(answer("worked\n"), answer(""), answer(""), answer(""))
    engine.main()
    [first] = folders(tmp_path)
    cli_ = fake_cli(answer("VERDICT: ok\n\nfine\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "kept", "--force",
                                      "--resume", first.name])
    assert engine.main() == 0
    assert argv_models(cli_.calls) == ["small-id"]
    last = every_line(tmp_path)[-1]
    assert (last["step"], last["model"]) == ("reviewer.md", "small-id")
    assert last["model_choice"]["from"] == "run"


def test_a_resume_asking_for_other_models_is_refused(
        tmp_path, monkeypatch, fake_cli, tiers, capsys):
    a_flow(tmp_path, monkeypatch, "moved", ["worker", "reviewer"],
           args=["--model-for", "reviewer=low"])
    no_waiting(monkeypatch)
    fake_cli(answer("worked\n"), answer(""), answer(""), answer(""))
    engine.main()
    [first] = folders(tmp_path)
    cli_ = fake_cli(answer("VERDICT: ok\n\nfine\n"))
    monkeypatch.setattr(sys, "argv", ["run.py", "moved", "--force",
                                      "--resume", first.name,
                                      "--model-for", "reviewer=high"])
    assert engine.main() == 1
    assert cli_.calls == []
    assert ("was started with reviewer=low, not reviewer=high"
            in capsys.readouterr().out)


def test_the_help_names_the_flag(capsys):
    cli.cmd_help()
    assert "--model-for" in capsys.readouterr().out
