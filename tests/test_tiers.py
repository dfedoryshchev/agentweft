import sys

sys.path.insert(0, ".")
from agentweft import providers, runner
from agentweft.flow import spec
from agentweft.orchestrate import workflow
from agentweft.providers import cli_provider
from agentweft.roles import resolver
from agentweft.runner import cli, prompts

TIERED = """name: tiered
steps:
  - role: planner
    prompt: planner.md
    model: mid
  - role: reviewer
    prompt: reviewer.md
    model: high
provider:
  provider: api
"""


def a_flow(tmp_path, text=TIERED):
    """a flow on disk, because Run reads the folder and not just the spec."""
    folder = tmp_path / "tiered"
    folder.mkdir()
    (folder / "flow.yaml").write_text(text, encoding="utf-8")
    (folder / "instructions.md").write_text("do the thing\n", encoding="utf-8")
    return folder


def a_run(tmp_path, provider=None):
    a_flow(tmp_path)
    # FLOW_ROOT and ROOT are one-item lists, so monkeypatch cannot hold them
    # and the repo's own tests put them back by hand.
    was = prompts.FLOW_ROOT[0]
    prompts.FLOW_ROOT[0] = str(tmp_path)
    try:
        fm = runner.config("tiered")
        by_role = resolver.resolve(fm.raw, prompts.flow_path("tiered"))
        return runner.Run("tiered", fm, by_role, provider=provider)
    finally:
        prompts.FLOW_ROOT[0] = was


def test_a_step_may_declare_a_model_tier():
    s = spec.load({"name": "x", "steps": [{"role": "planner", "model": "mid"}]})
    assert s.steps[0]["model"] == "mid"


def test_a_model_name_where_a_tier_belongs_is_refused():
    """the point of a tier is that it is not a version string.

    `model: opus` in a flow file is the thing the workflow header says was
    taken out of the prompts on the way over, arriving again by the back door.
    """
    bad = spec.check({"name": "x", "steps": [{"role": "planner", "model": "opus"}]})
    assert bad == ["step 0: model should be one of high, mid, low"]


def test_the_tier_picks_the_model_id_out_of_the_environment(monkeypatch):
    monkeypatch.setenv("MODEL_HIGH", "a-big-one")
    monkeypatch.setenv("MODEL", "the-only-one")
    p = providers.build({"provider": "api"}, tier="high")
    assert p._model() == "a-big-one"


def test_a_tier_with_nothing_behind_it_falls_back_to_the_one_model_there_is(monkeypatch):
    """a tier is a preference, not a requirement. one model configured is the
    normal case and it answers for every tier."""
    monkeypatch.delenv("MODEL_MID", raising=False)
    monkeypatch.setenv("MODEL", "the-only-one")
    p = providers.build({"provider": "api"}, tier="mid")
    assert p._model() == "the-only-one"


def test_a_model_named_in_the_flow_file_still_wins(monkeypatch):
    """same order as every other setting: the more specific source wins.

    `provider: {model: ...}` names one model. `model: high` asks for a class of
    model. saying both means you have already answered the question.
    """
    monkeypatch.setenv("MODEL_HIGH", "a-big-one")
    p = providers.build({"provider": "api", "model": "the-one-i-said"}, tier="high")
    assert p._model() == "the-one-i-said"


def test_the_check_says_which_tier_it_could_not_resolve(monkeypatch):
    monkeypatch.setenv("API_KEY", "x")
    monkeypatch.delenv("MODEL_HIGH", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    ok, detail = providers.build({"provider": "api"}, tier="high").check()
    assert not ok
    assert "MODEL_HIGH" in detail


def test_the_cli_is_handed_a_command_and_the_tier_changes_nothing(monkeypatch):
    """a tier is a model choice and the cli provider is given a command.

    there is no flag here that is ours to add - the command is whatever the
    flow named - so the tier is carried and not used, and that is written down
    rather than left to be discovered.
    """
    seen = []

    class Done(object):
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(argv, **kw):
        seen.append(argv)
        return Done()

    monkeypatch.setattr(cli_provider.subprocess, "run", fake_run)
    p = providers.build({"provider": "cli", "command": "echo"}, tier="high")
    p.ask("hi")
    assert seen == [["echo", "-p", "hi"]]
    assert p.opts["tier"] == "high"


def test_the_agent_file_tier_arrives_as_a_flow_step():
    seat = workflow.Agent("architect")
    assert seat.declared()["model"] == "high"
    assert seat.step() == {"role": "architect", "model": "high"}


def test_an_agent_with_no_file_declares_nothing():
    seat = workflow.Agent("nobody")
    assert seat.declared() == {}
    assert seat.step() == {"role": "nobody"}


def test_every_seat_carries_the_tier_its_own_file_declares():
    wf = workflow.load()
    for phase in wf.phases:
        for seat, step in zip(phase.agents, phase.spec.steps):
            assert step.get("model") == seat.declared().get("model"), seat.name
    tiers = sorted(set(s.get("model") for p in wf.phases for s in p.spec.steps))
    assert tiers == ["high", "mid"]


def test_the_vocabulary_walk_opens_the_agent_files_too():
    """the phase side is two files, and only one of them was ever read.

    `terms()` is a fact about the file, so it has to be a fact about both of
    them: the seat is named in workflow.yaml and everything about the seat is
    in the agent's own frontmatter.
    """
    words = workflow.terms()
    assert "agent.model" in words
    assert "agent.tools" in words
    assert "agent.name" in words


def test_a_file_whose_frontmatter_names_someone_else_is_countable(tmp_path):
    """a copied agent file with a stale name reads the wrong seat's tier.

    countable rather than raised, same as `uncriteried()` - it is a gap in the
    files, not a failure of the loader.
    """
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "architect.md").write_text(
        "---\nname: builder\nmodel: high\ntools: [read]\n---\n", encoding="utf-8")
    was = workflow.ROOT[0]
    workflow.ROOT[0] = str(tmp_path)
    try:
        wf = workflow.Workflow({"name": "x",
                                "phases": [{"name": "p", "agents": ["architect"]}]})
        assert [a.name for a in workflow.misnamed(wf)] == ["architect"]
    finally:
        workflow.ROOT[0] = was


def test_every_shipped_agent_file_names_itself():
    assert workflow.misnamed() == []


def test_a_step_with_a_tier_gets_a_provider_that_knows_it(tmp_path):
    """the tier has to reach a provider or it is decoration again.

    the step names no provider of its own, so before this the step had no
    entry in `by_step` at all and the tier had nowhere to be read.
    """
    run = a_run(tmp_path)
    assert run.by_step["planner.md"].opts["tier"] == "mid"
    assert run.by_step["reviewer.md"].opts["tier"] == "high"
    assert run.by_step["planner.md"].name == "api"


def test_the_provider_check_asks_about_each_tier_it_finds(tmp_path, capsys, monkeypatch):
    """a tier is configuration, so `run.py provider` has to see it.

    the flow's block is usable and the two tiers are not, which is exactly the
    case that used to pass this command and then fail at the step.
    """
    a_flow(tmp_path)
    monkeypatch.setenv("API_KEY", "x")
    monkeypatch.setenv("MODEL", "the-only-one")
    monkeypatch.delenv("MODEL_HIGH", raising=False)
    monkeypatch.delenv("MODEL_MID", raising=False)
    was = prompts.FLOW_ROOT[0]
    prompts.FLOW_ROOT[0] = str(tmp_path)
    try:
        assert cli.cmd_provider() == 0
    finally:
        prompts.FLOW_ROOT[0] = was
    lines = [l for l in capsys.readouterr().out.split("\n") if l.strip()]
    assert lines == ["  ok   api  the-only-one",
                     "  ok   api mid  the-only-one",
                     "  ok   api high  the-only-one"]


def test_a_tier_nothing_answers_for_fails_the_check_on_its_own_line(tmp_path, capsys,
                                                                    monkeypatch):
    a_flow(tmp_path)
    monkeypatch.setenv("API_KEY", "x")
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("MODEL_HIGH", raising=False)
    monkeypatch.setenv("MODEL_MID", "a-small-one")
    was = prompts.FLOW_ROOT[0]
    prompts.FLOW_ROOT[0] = str(tmp_path)
    try:
        cli.cmd_provider()
    finally:
        prompts.FLOW_ROOT[0] = was
    lines = [l for l in capsys.readouterr().out.split("\n") if l.strip()]
    assert lines[1] == "  ok   api mid  a-small-one"
    assert lines[2].startswith("  FAIL api high")
    assert "MODEL_HIGH" in lines[2]


def test_a_pinned_provider_still_replaces_the_tiered_one(tmp_path):
    """half a run on the pinned provider and half on the flow's own is not a
    comparison of anything - the tier does not buy an exception to that."""
    run = a_run(tmp_path, provider={"provider": "fake"})
    assert run.by_step["planner.md"].name == "fake"
    assert run.provider.name == "fake"
