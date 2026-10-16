"""how much a step says back: `verbosity: terse` asks for less in the prompt
and caps the answer, and a step that says nothing is asked as before."""
import sys

sys.path.insert(0, ".")
from agentweft.evals import recording
from agentweft.flow import spec
from agentweft.providers import cli_provider
from agentweft.roles import resolver
from agentweft.runner import engine

from test_effort import WHOLE, an_api, no_levels  # noqa: F401
from test_trace import a_flow, answer, every_line

API = "provider:\n  provider: api\n  model: m\n"


def terse():
    """-> the words a terse step is given."""
    return resolver.fragment("terse").strip()


def api_flow(tmp_path, monkeypatch, steps):
    a_flow(tmp_path, monkeypatch, "api", steps, tail=API)
    _, sent = an_api(monkeypatch, WHOLE)
    bodies = []
    post = sent.post

    def keep(url, json=None, timeout=None, headers=None):
        bodies.append(json)
        return post(url, json=json, timeout=timeout, headers=headers)

    monkeypatch.setattr(engine.providers.api_provider.httpx, "post", keep)
    return bodies


def asked(body):
    return body["messages"][0]["content"]


# what the flow may say


def test_a_step_may_be_terse_and_nothing_else_is_a_load_error():
    ok = {"name": "x", "steps": [{"role": "worker", "verbosity": "terse"},
                                 {"role": "reviewer",
                                  "verbosity": "normal"}]}
    assert spec.check(ok) == []
    bad = {"name": "x", "steps": [{"role": "worker", "verbosity": "short"}]}
    assert spec.check(bad) == [
        "step 0: verbosity should be one of normal, terse"]


def test_an_unknown_verbosity_stops_the_run_before_anything_is_asked(
        tmp_path, monkeypatch, fake_cli, no_levels, capsys):
    a_flow(tmp_path, monkeypatch, "typo", ["worker\nverbosity: quiet"])
    cli = fake_cli(answer("should not be asked\n"))
    assert engine.main() == 1
    assert cli.calls == []
    assert "verbosity should be one of normal, terse" in capsys.readouterr().out


# what reaches the api


def test_a_terse_step_is_told_so_and_capped(tmp_path, monkeypatch,
                                            no_levels):
    bodies = api_flow(tmp_path, monkeypatch,
                      ["outliner\nverbosity: terse", "worker"])
    assert engine.main() == 0
    outliner, worker = bodies
    assert terse() in asked(outliner)
    assert outliner["max_tokens"] == 8000
    assert terse() not in asked(worker)
    assert worker["max_tokens"] == 32000
    assert every_line(tmp_path)[0]["verbosity"] == {
        "asked": "terse", "limit": 8000, "applies": True}
    assert every_line(tmp_path)[1]["verbosity"] is None


def test_a_terse_step_that_thinks_hard_keeps_room_to_think(
        tmp_path, monkeypatch, no_levels):
    bodies = api_flow(tmp_path, monkeypatch,
                      ["worker\nverbosity: terse\neffort: high"])
    assert engine.main() == 0
    assert bodies[0]["max_tokens"] == 16000
    assert bodies[0]["output_config"] == {"effort": "high"}


def test_a_provider_cap_lower_than_terse_is_kept(monkeypatch, no_levels):
    p, sent = an_api(monkeypatch, WHOLE, max_tokens=2000)
    p.terse = True
    p.ask("x")
    assert sent.body["max_tokens"] == 2000


def test_nothing_said_asks_as_before(tmp_path, monkeypatch, no_levels):
    bodies = api_flow(tmp_path, monkeypatch, ["worker"])
    assert engine.main() == 0
    assert terse() not in asked(bodies[0])
    assert bodies[0]["max_tokens"] == 32000
    assert every_line(tmp_path)[0]["verbosity"] is None


# what reaches the cli


def test_claude_gets_the_terse_cap_in_its_environment(
        tmp_path, monkeypatch, fake_cli, no_levels):
    a_flow(tmp_path, monkeypatch, "cli", ["worker\nverbosity: terse",
                                          "reviewer"])
    cli = fake_cli(answer("did it\n"), answer("VERDICT: ok\n"))
    assert engine.main() == 0
    worker, reviewer = cli.calls
    assert terse() in worker["stdin"].decode("utf-8")
    assert worker["kw"]["env"][cli_provider.CAP_VAR] == "8000"
    assert cli_provider.CAP_VAR not in reviewer["kw"]["env"]
    assert every_line(tmp_path)[0]["verbosity"]["applies"] is True


def test_a_terse_step_sets_the_cap_over_the_parents(monkeypatch, no_levels):
    monkeypatch.setenv(cli_provider.CAP_VAR, "50000")
    p = cli_provider.CliProvider()
    assert p.child_env()[cli_provider.CAP_VAR] == "50000"
    p.terse = True
    assert p.child_env()[cli_provider.CAP_VAR] == "8000"


def test_terse_never_raises_a_lower_cap_the_run_set(monkeypatch, no_levels):
    monkeypatch.setenv(cli_provider.CAP_VAR, "4000")
    p = cli_provider.CliProvider()
    assert p.child_env()[cli_provider.CAP_VAR] == "4000"
    p.terse = True
    assert p.output_limit() == 4000
    assert p.child_env()[cli_provider.CAP_VAR] == "4000"


def test_a_recorded_terse_step_keeps_its_cap(monkeypatch, no_levels):
    r = recording.Recorder(cli_provider.CliProvider())
    r.terse = True
    assert r.output_limit() == 8000
    assert r.inner.child_env()[cli_provider.CAP_VAR] == "8000"


def test_a_command_that_is_not_claude_says_it_cannot_cap(
        tmp_path, monkeypatch, fake_cli, no_levels):
    a_flow(tmp_path, monkeypatch, "other", ["worker\nverbosity: terse"],
           tail="provider:\n  provider: cli\n  command: mycli\n")
    cli = fake_cli((0, b"did it\n", b""))
    assert engine.main() == 0
    assert terse() in cli.calls[0]["argv"][2]
    assert cli_provider.CAP_VAR not in cli.calls[0]["kw"]["env"]
    assert every_line(tmp_path)[0]["verbosity"] == {
        "asked": "terse", "limit": None, "applies": False}


def test_the_terse_words_leave_the_answer_shape_alone():
    assert "handoff" in terse() and "VERDICT" in terse()
