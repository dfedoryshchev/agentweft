"""`agentweft init`, the settings it writes, and the quick start it prints."""
import builtins
import hashlib
import os
import re
import shlex
import subprocess
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
    assert got == {"AGENTWEFT_PROVIDER": "cli",
                   "AGENTWEFT_PERMISSION_MODE": "dontAsk",
                   "AGENTWEFT_CO_AUTHOR": "false",
                   "AGENTWEFT_MAX_CALLS": "25", "AGENTWEFT_MAX_TOKENS": "0",
                   "AGENTWEFT_TESTS_E2E": "false", "AGENTWEFT_COMMITS": "none"}
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
    assert (got["MODEL_HIGH"], got["MODEL_MID"]) == ("opus", "sonnet")
    assert "MODEL_LOW" not in got
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


def test_a_blank_model_leaves_a_shell_export_standing(place, monkeypatch):
    (place / ".env").write_text("MODEL_HIGH=sonnet\n", encoding="utf-8")
    os.environ["MODEL_HIGH"] = "opus"
    assert agentweft(monkeypatch, "init", "--yes", "--force") == 0
    assert "MODEL_HIGH" not in (place / ".env").read_text(encoding="utf-8")
    engine.load_env()
    assert os.environ["MODEL_HIGH"] == "opus"


def a_host_project(place):
    files = {"CLAUDE.md": "# house rules\n",
             ".claude/settings.json": '{"permissions": {"allow": []}}\n',
             "README.md": "# host\n",
             "pyproject.toml": "[project]\nname = \"host\"\n",
             "tests/test_host.py": "def test_host():\n    assert True\n"}
    for rel, text in files.items():
        (place / rel).parent.mkdir(parents=True, exist_ok=True)
        (place / rel).write_bytes(text.encode("utf-8"))


def hashes(place):
    return {p.relative_to(place).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in place.rglob("*") if p.is_file()}


def test_init_leaves_a_projects_own_files_byte_identical(place, monkeypatch,
                                                          capsys):
    a_host_project(place)
    before = hashes(place)
    answers(monkeypatch, *[""] * len(init.QUESTIONS) + ["y"])
    assert agentweft(monkeypatch, "init") == 0
    after = hashes(place)
    assert {k: after[k] for k in before} == before
    assert set(after) - set(before) == {".env", "prices.yaml"}
    capsys.readouterr()

    assert agentweft(monkeypatch, "init", "--yes") == 1
    assert hashes(place) == after
    assert "init does not write over it" in capsys.readouterr().out

    (place / "prices.yaml").write_bytes(b"mine: 1\n")
    edited = hashes(place)
    answers(monkeypatch, *[""] * len(init.QUESTIONS) + ["y"])
    assert agentweft(monkeypatch, "init", "--force") == 0
    assert hashes(place) == edited


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


def test_the_real_task_line_init_prints_finds_its_flow(place, monkeypatch,
                                                       capsys):
    assert agentweft(monkeypatch, "init", "--yes") == 0
    line = [l.strip() for l in capsys.readouterr().out.splitlines()
            if l.strip().startswith("agentweft fix-with-test")]
    assert len(line) == 1
    argv = shlex.split(line[0], posix=os.name != "nt")
    assert "--flows" in argv
    flows = Path(argv[argv.index("--flows") + 1])
    assert (flows / "fix-with-test" / "flow.yaml").is_file()


def test_a_run_where_its_flows_folder_is_not_says_so(place, monkeypatch,
                                                     capsys):
    assert agentweft(monkeypatch, "minimal", "--force", "--flows",
                     "examples") == 1
    out = capsys.readouterr().out
    assert "no flow called minimal in examples" in out
    assert "--flows" in out


def test_list_with_no_flows_folder_says_where_it_looked(place, monkeypatch,
                                                        capsys):
    assert agentweft(monkeypatch, "list", "--flows", "flows") == 1
    out = capsys.readouterr().out
    assert "no flows in flows" in out
    assert "--flows" in out


def test_provider_with_no_flows_folder_says_so(place, monkeypatch, capsys):
    assert agentweft(monkeypatch, "provider", "--flows", "flows") == 1
    assert "no flows in flows" in capsys.readouterr().out


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


def test_the_falses_init_writes_read_as_false(place, monkeypatch):
    assert agentweft(monkeypatch, "init", "--yes") == 0
    engine.load_env()
    assert settings.get("co_author") is False
    assert settings.get("tests_e2e") is False


def test_init_answers_reach_the_run(place, monkeypatch, fake_cli):
    assert agentweft(monkeypatch, "init", "--yes", "--force") == 0
    (place / ".env").write_text(
        (place / ".env").read_text(encoding="utf-8")
        .replace("AGENTWEFT_CO_AUTHOR=false", "AGENTWEFT_CO_AUTHOR=true")
        .replace("dontAsk", "acceptEdits")
        .replace("AGENTWEFT_PROVIDER=cli", "AGENTWEFT_PROVIDER=fake")
        + "AGENTWEFT_SPEC_GLOBS=docs/rfc*\n",
        encoding="utf-8")
    # answers looser than the defaults are the person's, read from a folder
    # the run's place is not in (`--workdir` elsewhere)
    engine.load_env(place.parent / "elsewhere")
    assert providers.build({}).name == "fake"
    cli_ = fake_cli(answer("ok\n"))
    providers.build({"provider": "cli", "command": "claude"},
                    grant=["read"]).ask("x")
    argv = cli_.calls[0]["argv"]
    assert argv[argv.index("--settings") + 1] == cli_provider.json.dumps(
        cli_provider.NO_SWITCH, separators=(",", ":"))
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert snapshot.is_spec("docs/rfc-1.md")
    assert not snapshot.is_spec("TASK.md")


def test_a_dot_env_in_the_place_cannot_loosen_the_run(tmp_path, monkeypatch,
                                                      fake_cli, capsys):
    from test_connectors import a_flow

    work = a_flow(tmp_path, monkeypatch,
                  [("worker", ["tools: [read, edit]"])])
    (work / ".env").write_text("AGENTWEFT_PERMISSION_MODE=bypassPermissions\n"
                               "AGENTWEFT_TIMEOUT=120\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.chdir(work)
    cli_ = fake_cli(answer("done\n"))
    assert engine.main() != 0
    assert cli_.calls == []
    said = capsys.readouterr().out
    assert ("AGENTWEFT_PERMISSION_MODE is set by "
            + str((work / ".env").resolve()) + ", inside the place: it loosens"
            " a guard, which is yours to set, in your own environment or a"
            " .env outside the place") in said
    assert "AGENTWEFT_TIMEOUT" not in said


STEERS = "picks which program runs or where its traffic goes"
NOT_READ = ("is not a preference agentweft reads; declare it under `env:` in"
            " project.yml if the project's tests read it")


def refused(work, name, why):
    return (name + " is set by " + str((work / ".env").resolve())
            + ", inside the place: it " + why
            + ("" if why == NOT_READ else ", which is yours to set, in your"
               " own environment or a .env outside the place"))


@pytest.mark.parametrize("name, value, why", [
    ("GIT_CONFIG_COUNT", "1", STEERS),
    ("GIT_CONFIG_KEY_0", "core.fsmonitor", STEERS),
    ("GIT_CONFIG_VALUE_0", "python x.py", STEERS),
    ("GIT_DIR", "x", STEERS), ("GIT_SSH_COMMAND", "x", STEERS),
    ("GIT_EXEC_PATH", "x", STEERS), ("PYTHONPATH", "x", STEERS),
    ("PYTHONSTARTUP", "x", STEERS), ("NODE_OPTIONS", "x", STEERS),
    ("BASH_ENV", "x", STEERS), ("LD_PRELOAD", "x", STEERS),
    ("DYLD_INSERT_LIBRARIES", "x", STEERS),
    ("DATABASE_URL", "sqlite://", NOT_READ),
    ("AGENTWEFT_PERMISSION_MODE", "bypassPermissions", "loosens a guard"),
    ("AGENTWEFT_MAX_CALLS", "0", "loosens a guard"),
    ("AGENTWEFT_MAX_TURNS", "0", "loosens a guard"),
    ("PRICES", "cheap.yaml", "loosens a guard"),
    ("AGENTWEFT_KEY_FILE", "~/.ssh/id_any",
     "picks a credential or where one is sent"),
    ("AGENTWEFT_PROVIDER", "api", "picks a credential or where one is sent"),
    ("API_KEY", "decoy-api-key-for-tests",
     "picks a credential or where one is sent"),
    ("API_URL", "https://elsewhere.example",
     "picks a credential or where one is sent"),
    ("ANTHROPIC_BASE_URL", "https://elsewhere.example",
     "picks a credential or where one is sent"),
    ("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB", "0",
     "picks a credential or where one is sent"),
    ("claude_config_dir", "decoy-config-folder",
     "picks a credential or where one is sent"),
    ("PATH", "bin", "picks which program runs or where its traffic goes"),
    ("HTTPS_PROXY", "http://elsewhere.example",
     "picks which program runs or where its traffic goes"),
    ("NODE_EXTRA_CA_CERTS", "ca.pem",
     "picks which program runs or where its traffic goes"),
    ("AGENTWEFT_COMMITS", "squash", "makes a decision that is yours"),
    ("AGENTWEFT_CO_AUTHOR", "true", "makes a decision that is yours"),
    ("AGENTWEFT_SOMETHING_NEW", "1", "is a setting agentweft has not"
     " classed as a preference"),
])
def test_what_a_place_s_dot_env_may_not_set(tmp_path, monkeypatch, name,
                                            value, why):
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("AGENTWEFT_TIMEOUT=120\n" + name + "=" + value
                               + "\n", encoding="utf-8")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("AGENTWEFT_TIMEOUT", raising=False)
    monkeypatch.chdir(work)
    with pytest.raises(ValueError) as e:
        engine.load_env(work)
    assert str(e.value) == refused(work, name, why)
    # refused whole: not even the preference beside it was applied
    assert name not in os.environ and "AGENTWEFT_TIMEOUT" not in os.environ


def test_a_place_env_that_steers_git_refuses_before_any_process(
        tmp_path, monkeypatch, capsys):
    from test_connectors import a_flow

    work = a_flow(tmp_path, monkeypatch, [("worker", [])])
    (work / ".env").write_text("GIT_CONFIG_COUNT=1\n"
                               "GIT_CONFIG_KEY_0=core.fsmonitor\n"
                               "GIT_CONFIG_VALUE_0=python x.py\n",
                               encoding="utf-8")
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.chdir(work)
    started = []

    def no_process(argv, *a, **kw):
        started.append(argv)
        raise OSError("no process in this test")

    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    assert engine.main() == 1
    assert started == []
    said = capsys.readouterr().out
    for name in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
        assert refused(work, name, STEERS) in said
        assert name not in os.environ


def test_a_dot_env_above_the_place_in_its_repo_is_the_projects(
        tmp_path, monkeypatch, capsys):
    from test_connectors import a_flow

    repo = a_flow(tmp_path, monkeypatch, [("worker", [])])
    (repo / ".git").mkdir()
    app = repo / "packages" / "app"
    app.mkdir(parents=True)
    (repo / ".env").write_text("GIT_CONFIG_COUNT=1\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["run.py", "two", "--force",
                                      "--workdir", str(app)])
    started = []

    def no_process(argv, *a, **kw):
        started.append(argv)
        raise OSError("no process in this test")

    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    assert engine.main() == 1
    assert started == []
    said = capsys.readouterr().out
    assert ("GIT_CONFIG_COUNT is set by " + str((repo / ".env").resolve())
            + ", in the repo the place is in: it " + STEERS) in said
    assert "GIT_CONFIG_COUNT" not in os.environ
    assert settings.STARTED_IN_PLACE is True


def a_place_whose_env_links_out(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "runs" / "an-earlier-run" / "tmp"
    outside.mkdir(parents=True)
    (outside / "x.env").write_text("GIT_DIR=/nowhere\n", encoding="utf-8")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.chdir(work)
    return work, outside / "x.env"


def test_a_dot_env_link_is_judged_where_it_sits_not_where_it_points(
        tmp_path, monkeypatch):
    work, target = a_place_whose_env_links_out(tmp_path, monkeypatch)
    (work / ".env").write_text(target.read_text(encoding="utf-8"),
                               encoding="utf-8")
    real = Path.resolve

    def as_a_link(self, *a, **kw):
        if self.name == ".env":
            return real(target, *a, **kw)
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "resolve", as_a_link)
    with pytest.raises(ValueError) as e:
        engine.load_env(".")
    assert "GIT_DIR is set by " + str(real(work) / ".env") in str(e.value)
    assert "GIT_DIR" not in os.environ or os.environ["GIT_DIR"] != "/nowhere"


def test_a_dot_env_symlink_out_of_the_place_is_still_the_places(
        tmp_path, monkeypatch):
    work, target = a_place_whose_env_links_out(tmp_path, monkeypatch)
    try:
        os.symlink(str(target), str(work / ".env"))
    except (OSError, NotImplementedError):
        pytest.skip("no right to make a symlink here")
    with pytest.raises(ValueError):
        engine.load_env(".")
    assert os.environ.get("GIT_DIR") != "/nowhere"


def test_a_name_project_yml_declares_reaches_the_tests_only(
        tmp_path, monkeypatch, fake_cli):
    from agentweft.guardrails.gates import base
    from test_connectors import a_flow

    work = a_flow(tmp_path, monkeypatch, [("worker", [])],
                  project_yml="project:\n  name: p\nenv: [DATABASE_URL]\n")
    (work / ".env").write_text("DATABASE_URL=sqlite://\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(work)
    cli_ = fake_cli(answer("done\n"))
    assert engine.main() == 0
    assert len(cli_.calls) == 1
    assert "DATABASE_URL" not in os.environ
    assert "DATABASE_URL" not in cli_.calls[0]["kw"]["env"]
    with base.fresh_python() as env:
        assert env["DATABASE_URL"] == "sqlite://"


def test_a_name_project_yml_declares_cannot_steer_a_program(tmp_path,
                                                            monkeypatch):
    from test_connectors import a_flow

    work = a_flow(tmp_path, monkeypatch, [("worker", [])],
                  project_yml="project:\n  name: p\nenv: [GIT_DIR]\n")
    (work / ".env").write_text("GIT_DIR=x\n", encoding="utf-8")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.chdir(work)
    with pytest.raises(ValueError) as e:
        engine.load_env(work)
    assert str(e.value) == refused(work, "GIT_DIR", STEERS)


@pytest.mark.parametrize("env, said", [
    ("DATABASE_URL", "env: should be a list"),
    (["DATABASE URL"], "env: DATABASE URL should be a variable name"),
    ([3], "env: 3 should be a variable name"),
])
def test_project_yml_env_is_a_list_of_names(env, said):
    from agentweft.orchestrate import project

    assert said in project.check({"project": {"name": "p"}, "env": env})


def test_the_provider_check_refuses_a_place_env_before_any_process(
        place, monkeypatch, fake_cli, capsys):
    (place / ".env").write_text("PATH=bin\n", encoding="utf-8")
    cli_ = fake_cli(answer("ok\n"))
    assert agentweft(monkeypatch, "provider", "--flows",
                     str(REPO / "examples")) == 1
    assert cli_.asides == [] and cli_.calls == []
    assert refused(place, "PATH", STEERS) in capsys.readouterr().out
    assert os.environ.get("PATH") != "bin"


def test_a_dot_env_outside_the_place_may_set_anything(tmp_path, monkeypatch,
                                                      fake_cli):
    from test_connectors import a_flow

    work = a_flow(tmp_path, monkeypatch, [("worker", ["tools: [read]"])])
    (tmp_path / ".env").write_text(
        "AGENTWEFT_PERMISSION_MODE=acceptEdits\nGIT_DIR_IGNORED_NAME=x\n",
        encoding="utf-8")
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(sys, "argv", sys.argv + ["--workdir", str(work)])
    cli_ = fake_cli(answer("done\n"))
    assert engine.main() == 0
    argv = cli_.calls[0]["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert os.environ["GIT_DIR_IGNORED_NAME"] == "x"


@pytest.mark.parametrize("text", ["JUSTANAME\n", "=value\n"])
@pytest.mark.parametrize("inside", [True, False])
def test_a_dot_env_line_that_is_not_name_equals_value_is_refused(
        tmp_path, monkeypatch, text, inside):
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("# a note\n\n" + text, encoding="utf-8")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.chdir(work)
    with pytest.raises(ValueError) as e:
        engine.load_env(work if inside else tmp_path / "elsewhere")
    assert str(e.value) == (str((work / ".env").resolve()) + " line 3 is"
                            " not NAME=value")


def test_preferences_in_a_place_s_dot_env_still_work(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text(
        "AGENTWEFT_TIMEOUT=120\nAGENTWEFT_RETRIES=1\nAGENTWEFT_WORKERS=2\n"
        "AGENTWEFT_TESTS_E2E=true\nAGENTWEFT_TESTS_INTEGRATION=off\n"
        "AGENTWEFT_SPEC_GLOBS=docs/rfc*\nMODEL=sonnet\nMODEL_HIGH=opus\n"
        "EFFORT_LOW=low\nPYTHONIOENCODING=utf-8\n",
        encoding="utf-8")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.chdir(work)
    engine.load_env(work)
    assert settings.get("timeout") == 120
    assert os.environ["MODEL_HIGH"] == "opus"
    assert snapshot.is_spec("docs/rfc-1.md")


def test_a_place_s_dot_env_may_hold_a_setting_no_looser_than_yours(
        tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.chdir(work)
    monkeypatch.setattr(sys, "argv", ["agentweft", "init", "--yes"])
    assert cli.entrypoint() == 0
    with open(work / ".env", "a", encoding="utf-8") as f:
        f.write("AGENTWEFT_MAX_TURNS=10\nAGENTWEFT_MAX_TOKENS=0\n")
    os.environ["AGENTWEFT_MAX_TOKENS"] = "50000"
    with pytest.raises(ValueError) as e:
        engine.load_env(work)
    assert str(e.value) == refused(work, "AGENTWEFT_MAX_TOKENS",
                                   "loosens a guard")
    os.environ["AGENTWEFT_MAX_TOKENS"] = "0"
    engine.load_env(work)
    assert os.environ["AGENTWEFT_MAX_TURNS"] == "10"
    assert not settings.allowed("AGENTWEFT_MAX_CALLS", "26")
    assert not settings.allowed("AGENTWEFT_MAX_CALLS", "many")
    assert settings.allowed("AGENTWEFT_PERMISSION_MODE", "dontAsk")


def text_of(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        return ",".join(value)
    return str(value)


def test_every_setting_is_a_preference_or_held_to_no_looser():
    for key, value in settings.DEFAULTS.items():
        name = settings.env_name(key)
        if name in settings.PREFERENCES:
            continue
        assert settings.allowed(name, text_of(value)), key
        assert not settings.allowed(name, "something-else-entirely"), key


def test_load_env_is_the_one_writer_of_the_run_s_environment():
    writes = re.compile(r"os\.environ\s*\[[^\]]*\]\s*=(?!=)"
                        r"|os\.environ\.(update|setdefault|pop|clear)\("
                        r"|os\.putenv\(")
    found = {}
    for path in sorted((REPO / "agentweft").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        hits = len(writes.findall(text))
        if hits:
            found[path.relative_to(REPO).as_posix()] = hits
    # the eval harness sets and puts back its own inbox for the case it
    # replays, not a run
    assert found == {"agentweft/runner/engine.py": 1,
                     "agentweft/evals/harness.py": 3}
    engine_text = (REPO / "agentweft" / "runner" / "engine.py").read_text(
        encoding="utf-8")
    body = engine_text.split("def load_env(", 1)[1].split("\ndef ", 1)[0]
    assert writes.search(body)


def test_with_nothing_set_the_defaults_stand(place, fake_cli):
    assert providers.build({}).name == "cli"
    cli_ = fake_cli(answer("ok\n"))
    providers.build({"provider": "cli", "command": "claude"},
                    grant=["read"]).ask("x")
    argv = cli_.calls[0]["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--settings") + 1] == cli_provider.json.dumps(
        dict(cli_provider.NO_SWITCH, **cli_provider.NO_TRAILER),
        separators=(",", ":"))
    assert snapshot.is_spec("TASK.md")
