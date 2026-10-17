"""`agentweft init`, the settings it writes, and the quick start it prints."""
import builtins
import os
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.guardrails import snapshot
from agentweft.providers import cli_provider
from agentweft.runner import cli, engine, init, prompts, settings

from test_trace import answer

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def place(tmp_path, monkeypatch):
    """a directory of its own to run in, and an environment `.env` cannot
    leak out of: `load_env` writes straight into os.environ."""
    monkeypatch.setattr(os, "environ", {k: v for k, v in os.environ.items()
                                        if not k.startswith(("AGENTWEFT_",
                                                             "MODEL"))})
    was = prompts.FLOW_ROOT[0]
    prompts.FLOW_ROOT[0] = str(REPO / "flows")
    work = tmp_path / "project"
    work.mkdir()
    monkeypatch.chdir(work)
    yield work
    prompts.FLOW_ROOT[0] = was


def agentweft(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["agentweft"] + list(args))
    return cli.entrypoint()


def written(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k] = v
    return out


def answers(monkeypatch, *said):
    left = list(said)
    asked = []

    def fake_input(prompt=""):
        asked.append(prompt)
        return left.pop(0)
    monkeypatch.setattr(builtins, "input", fake_input)
    return asked


# init


def test_init_yes_writes_every_setting_with_its_default(place, monkeypatch,
                                                         capsys):
    assert agentweft(monkeypatch, "init", "--yes") == 0
    got = written(place / ".env")
    assert got == {"AGENTWEFT_PROVIDER": "cli", "MODEL_HIGH": "",
                   "MODEL_MID": "", "MODEL_LOW": "",
                   "AGENTWEFT_PERMISSION_MODE": "dontAsk",
                   "AGENTWEFT_CO_AUTHOR": "false",
                   "AGENTWEFT_MAX_CALLS": "25", "AGENTWEFT_MAX_TOKENS": "0",
                   "AGENTWEFT_TESTS_E2E": "false", "AGENTWEFT_COMMITS": "none",
                   "AGENTWEFT_SPEC_GLOBS": "TASK.md,SPEC*.md,docs/spec*"}
    assert not (place / "prices.yaml").exists()
    out = capsys.readouterr().out
    assert "agentweft minimal --force --flows" in out
    assert "agentweft fix-with-test --workdir" in out


def test_init_yes_asks_nothing(place, monkeypatch):
    asked = answers(monkeypatch)
    assert agentweft(monkeypatch, "init", "--yes") == 0
    assert asked == []


def test_init_never_overwrites_without_force(place, monkeypatch, capsys):
    (place / ".env").write_text("API_KEY=mine\n", encoding="utf-8")
    assert agentweft(monkeypatch, "init", "--yes") == 1
    assert (place / ".env").read_text(encoding="utf-8") == "API_KEY=mine\n"
    assert "--force" in capsys.readouterr().out
    assert agentweft(monkeypatch, "init", "--yes", "--force") == 0
    got = written(place / ".env")
    assert got["AGENTWEFT_COMMITS"] == "none"
    assert got["API_KEY"] == "mine"


def test_init_writes_what_it_was_told_and_asks_again_on_a_wrong_answer(
        place, monkeypatch):
    asked = answers(monkeypatch, "api", "opus", "sonnet", "", "acceptEdits",
                    "y", "40", "100000", "yes", "often", "squash",
                    "SPEC.md, docs/rfc*", "y")
    assert agentweft(monkeypatch, "init") == 0
    got = written(place / ".env")
    assert got["AGENTWEFT_PROVIDER"] == "api"
    assert (got["MODEL_HIGH"], got["MODEL_MID"], got["MODEL_LOW"]) == \
        ("opus", "sonnet", "")
    assert got["AGENTWEFT_PERMISSION_MODE"] == "acceptEdits"
    assert got["AGENTWEFT_CO_AUTHOR"] == "true"
    assert (got["AGENTWEFT_MAX_CALLS"], got["AGENTWEFT_MAX_TOKENS"]) == \
        ("40", "100000")
    assert got["AGENTWEFT_TESTS_E2E"] == "true"
    assert got["AGENTWEFT_COMMITS"] == "squash"
    assert got["AGENTWEFT_SPEC_GLOBS"] == "SPEC.md,docs/rfc*"
    assert (place / "prices.yaml").is_file()
    assert sum("commit" in a for a in asked) == 2


def test_init_force_keeps_a_price_table_already_there(place, monkeypatch,
                                                     capsys):
    (place / ".env").write_text("API_KEY=x\n", encoding="utf-8")
    (place / "prices.yaml").write_text("mine: 1\n", encoding="utf-8")
    answers(monkeypatch, *[""] * len(init.QUESTIONS) + ["y"])
    assert agentweft(monkeypatch, "init", "--force") == 0
    assert (place / "prices.yaml").read_text(encoding="utf-8") == "mine: 1\n"
    assert "prices.yaml is already here" in capsys.readouterr().out


def test_the_permission_modes_offered_are_the_ones_claude_takes():
    assert init.PERMISSION_MODES == ("dontAsk", "acceptEdits", "auto",
                                     "bypassPermissions", "manual", "plan")


def test_the_quick_start_init_prints_ends_green(place, monkeypatch, capsys):
    assert agentweft(monkeypatch, "init", "--yes") == 0
    printed = capsys.readouterr().out
    fake = [l.strip() for l in printed.splitlines()
            if l.strip().startswith("agentweft minimal")]
    assert len(fake) == 1
    argv = shlex.split(fake[0], posix=os.name != "nt")
    assert agentweft(monkeypatch, *argv[1:]) == 0
    assert ": done" in capsys.readouterr().out


# no args, --flows, step --workdir


def test_no_args_prints_help_and_calls_nothing(place, monkeypatch, capsys):
    def no_provider(*a, **kw):
        pytest.fail("a bare run built a provider")
    monkeypatch.setattr(providers, "build", no_provider)
    monkeypatch.setattr(sys, "argv", ["run.py"])
    assert engine.main() == 0
    assert "usage" in capsys.readouterr().out
    assert agentweft(monkeypatch) == 0
    assert "agentweft init" in capsys.readouterr().out


def test_show_reads_the_examples_with_flows(place, monkeypatch, capsys):
    assert agentweft(monkeypatch, "show", "minimal", "--flows",
                     str(REPO / "examples")) == 0
    assert "one paragraph" in capsys.readouterr().out


def test_step_works_in_the_workdir_it_is_given(place, monkeypatch, tmp_path):
    seen = {}

    class Caught(Exception):
        pass

    def fake_run(flow, spec, by_role, **kw):
        seen.update(kw)
        raise Caught()
    monkeypatch.setattr(engine, "Run", fake_run)
    with pytest.raises(Caught):
        agentweft(monkeypatch, "step", "minimal", "worker", "--flows",
                  str(REPO / "examples"), "--workdir", str(tmp_path))
    assert seen["workdir"] == str(tmp_path)


# the environment level


def test_a_setting_comes_from_the_environment_under_the_flow(place):
    os.environ["AGENTWEFT_MAX_CALLS"] = "7"
    os.environ["AGENTWEFT_TESTS_E2E"] = "true"
    assert settings.get("max_calls") == 7
    assert settings.get("max_calls", flow={"max_calls": 3}) == 3
    assert settings.get("tests_e2e") is True
    assert settings.get("max_calls", env=9) == 9


def test_a_key_the_defaults_do_not_know_comes_back_as_written(place):
    os.environ["AGENTWEFT_COMMITS"] = "wip"
    assert settings.get("commits") == "wip"


def test_init_answers_reach_the_run(place, monkeypatch, fake_cli):
    assert agentweft(monkeypatch, "init", "--yes", "--force") == 0
    (place / ".env").write_text(
        (place / ".env").read_text(encoding="utf-8")
        .replace("AGENTWEFT_CO_AUTHOR=false", "AGENTWEFT_CO_AUTHOR=true")
        .replace("dontAsk", "acceptEdits")
        .replace("AGENTWEFT_PROVIDER=cli", "AGENTWEFT_PROVIDER=fake")
        .replace("TASK.md,SPEC*.md,docs/spec*", "docs/rfc*"),
        encoding="utf-8")
    engine.load_env()
    assert providers.build({}).name == "fake"
    cli_ = fake_cli(answer("ok\n"))
    providers.build({"provider": "cli", "command": "claude"},
                    grant=["read"]).ask("x")
    argv = cli_.calls[0]["argv"]
    assert "--settings" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert snapshot.is_spec("docs/rfc-1.md")
    assert not snapshot.is_spec("TASK.md")


def test_with_nothing_set_the_defaults_stand(place, fake_cli):
    assert providers.build({}).name == "cli"
    cli_ = fake_cli(answer("ok\n"))
    providers.build({"provider": "cli", "command": "claude"},
                    grant=["read"]).ask("x")
    argv = cli_.calls[0]["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--settings") + 1] == cli_provider.json.dumps(
        cli_provider.NO_TRAILER, separators=(",", ":"))
    assert snapshot.is_spec("TASK.md")
