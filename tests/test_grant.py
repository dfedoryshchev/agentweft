"""a step's grant, handed to `claude` as its own permission flags."""
import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft import providers, runner
from agentweft.flow import spec
from agentweft.providers import cli_provider
from agentweft.roles import resolver
from agentweft.runner import cli, engine, prompts

from test_trace import a_flow, answer, folders, lines


def claude(grant=None, **opts):
    return providers.build(dict({"provider": "cli", "command": "claude"},
                                **opts), grant=grant)


def flag(argv, name):
    """-> the value after a flag, or None when the flag is not there."""
    return argv[argv.index(name) + 1] if name in argv else None


# which tools a grant word is


def test_every_grant_word_names_the_cli_tools_it_stands_for():
    assert tuple(cli_provider.TOOLS) == spec.GRANTS
    for word, tools in cli_provider.TOOLS.items():
        assert tools, word


# the fence


def test_a_step_granted_read_is_fenced_in_its_argv(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read"]).ask("look")
    argv = cli_.calls[0]["argv"]
    assert flag(argv, "--tools") == "Read,Glob"
    assert flag(argv, "--allowedTools") == "Read,Glob"
    assert flag(argv, "--permission-mode") == "dontAsk"
    assert flag(argv, "--disallowedTools") == "mcp__*"
    for alone in ("--strict-mcp-config", "--disable-slash-commands",
                  "--restricted"):
        assert alone in argv, alone
    # restricted already loads no user, project or local file
    assert "--setting-sources" not in argv
    assert cli_.calls[0]["stdin"] == b"look"


def test_a_step_granted_a_shell_keeps_it_and_loads_only_user_settings(
        fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read", "grep", "shell"]).ask("run it")
    argv = cli_.calls[0]["argv"]
    tools = flag(argv, "--tools").split(",")
    assert tools == ["Read", "Glob", "Grep", "Bash", "PowerShell"]
    assert flag(argv, "--allowedTools").split(",") == tools
    assert flag(argv, "--setting-sources") == "user"
    assert "--restricted" not in argv
    assert flag(argv, "--permission-mode") == "dontAsk"


def test_a_grant_of_nothing_takes_every_tool_away(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=[]).ask("think")
    argv = cli_.calls[0]["argv"]
    assert flag(argv, "--tools") == ""
    assert "--allowedTools" not in argv
    assert "--restricted" in argv


def test_a_step_with_no_grant_keeps_the_hosts_own_default(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    claude().ask("x")
    argv = cli_.calls[0]["argv"]
    for name in ("--tools", "--allowedTools", "--permission-mode",
                 "--restricted", "--setting-sources"):
        assert name not in argv, name
    assert cli_.asides == []


def test_the_model_flag_stays_last(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read"], model="m").ask("x")
    assert cli_.calls[0]["argv"][-2:] == ["--model", "m"]


def a_settings_file(tmp_path, monkeypatch, said):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(said), encoding="utf-8")
    monkeypatch.setattr(cli_provider, "USER_SETTINGS", str(path))
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)


def test_a_step_that_only_looks_runs_on_the_model_the_persons_file_names(
        fake_cli, tmp_path, monkeypatch):
    a_settings_file(tmp_path, monkeypatch, {"model": "opus"})
    cli_ = fake_cli(answer("ok\n"), answer("ok\n"))
    claude(grant=["read"]).ask("x")
    claude(grant=["read", "shell"]).ask("x")
    looks, acts = [c["argv"] for c in cli_.calls]
    assert "--restricted" in looks and flag(looks, "--model") == "opus"
    # the user settings load there, and with them its model
    assert "--model" not in acts


def test_a_model_the_step_was_given_wins_over_the_persons_file(
        fake_cli, tmp_path, monkeypatch):
    a_settings_file(tmp_path, monkeypatch, {"model": "opus"})
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read"], model="m").ask("x")
    assert flag(cli_.calls[0]["argv"], "--model") == "m"


@pytest.mark.parametrize("said", [{}, {"model": ""}, "not json"])
def test_a_file_that_names_no_model_leaves_the_cli_default(
        fake_cli, tmp_path, monkeypatch, said):
    a_settings_file(tmp_path, monkeypatch, said)
    if said == "not json":
        (tmp_path / "settings.json").write_text("{", encoding="utf-8")
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read"]).ask("x")
    assert "--model" not in cli_.calls[0]["argv"]


def test_a_model_in_the_environment_is_left_to_the_cli(fake_cli, tmp_path,
                                                       monkeypatch):
    a_settings_file(tmp_path, monkeypatch, {"model": "opus"})
    monkeypatch.setenv("ANTHROPIC_MODEL", "sonnet")
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read"]).ask("x")
    assert "--model" not in cli_.calls[0]["argv"]


def test_another_command_gets_no_fence_and_no_version_call(fake_cli):
    cli_ = fake_cli((0, b"-p hi\n", b""))
    p = providers.build({"provider": "cli", "command": "echo"},
                        grant=["read"])
    p.ask("hi")
    assert cli_.calls[0]["argv"] == ["echo", "-p", "hi"]
    assert cli_.asides == []
    assert p.granted() == {"tools": ["read"], "enforced": False,
                           "argv": None, "cli_version": None,
                           "shell_writes": None}


# the settings handed over


def test_the_co_author_trailer_is_off_unless_the_run_opts_in(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read"]).ask("x")
    claude().ask("x")
    for call in cli_.calls:
        said = json.loads(flag(call["argv"], "--settings"))
        assert said == {"switchModelsOnFlag": False,
                        "attribution": {"commit": "", "pr": "",
                                        "sessionUrl": False}}


def test_a_run_that_opts_in_keeps_the_cli_default_trailer(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    claude(co_author=True).ask("x")
    said = json.loads(flag(cli_.calls[0]["argv"], "--settings"))
    assert said == {"switchModelsOnFlag": False}


def test_the_settings_never_switch_hooks_off(fake_cli):
    """a hook this run installs has to keep running; the target's own are
    kept out by which setting sources load."""
    cli_ = fake_cli(answer("ok\n"))
    claude(grant=["read", "shell"]).ask("x")
    assert "disableAllHooks" not in flag(cli_.calls[0]["argv"], "--settings")


# the version floor


def test_a_cli_below_the_floor_is_refused_before_the_call(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    cli_.version = (0, b"2.1.294 (Claude Code)\n", b"")
    r = claude(grant=["read"]).ask("x")
    assert not r and r.retryable is False
    assert "2.1.294" in r.detail and "2.1.295" in r.detail
    assert cli_.calls == []
    assert cli_.asides == [["claude", "--version"]]


def test_a_version_that_cannot_be_read_is_refused_too(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    cli_.version = (0, b"something else\n", b"")
    r = claude(grant=["read"]).ask("x")
    assert not r and cli_.calls == []


def test_the_version_is_asked_once_per_provider(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    p = claude(grant=["read"])
    p.ask("x")
    p.ask("y")
    assert cli_.asides == [["claude", "--version"]]
    assert len(cli_.calls) == 2


def test_an_ungranted_step_is_not_held_to_the_floor(fake_cli):
    cli_ = fake_cli(answer("ok\n"))
    cli_.version = (0, b"2.1.200 (Claude Code)\n", b"")
    assert claude().ask("x")


# a run


def test_the_run_record_keeps_the_grant_and_what_was_passed(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "granted",
           ["worker\ntools: [read]", "reviewer"])
    cli_ = fake_cli(answer("did it\n"), answer("VERDICT: ok\n\nfine\n"))
    engine.main()
    asked = cli_.calls[0]["argv"]
    assert flag(asked, "--permission-mode") == "dontAsk"
    assert flag(asked, "--tools") == "Read,Glob"
    assert "--tools" not in cli_.calls[1]["argv"]
    first, second = lines(folders(tmp_path)[0])
    assert first["grant"]["argv"] == asked[1:]
    said = first["grant"]
    assert said["tools"] == ["read"] and said["enforced"] is True
    assert said["cli_version"] == "2.1.296"
    assert said["argv"][:4] == ["-p", "--output-format", "json", "--settings"]
    assert flag(said["argv"], "--permission-mode") == "dontAsk"
    assert second["grant"] is None


def test_a_run_on_an_old_cli_stops_refused_at_the_granted_step(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "old",
           ["worker\ntools: [read]", "reviewer"])
    cli_ = fake_cli(answer("did it\n"))
    cli_.version = (0, b"2.1.294 (Claude Code)\n", b"")
    engine.main()
    [line] = lines(folders(tmp_path)[0])
    assert line["outcome"] == "refused" and line["step"] == "worker.md"
    assert "2.1.294" in line["why"]
    assert cli_.calls == []


def test_a_pinned_provider_still_carries_each_steps_grant(tmp_path,
                                                         monkeypatch):
    a_flow(tmp_path, monkeypatch, "pinned",
           ["worker\ntools: [read]", "reviewer"])
    fm = runner.config("pinned")
    run = engine.Run("pinned", fm, {"worker": "", "reviewer": ""},
                     provider={"provider": "cli", "command": "claude"})
    assert run.by_step["worker.md"].grant == ["read"]
    assert run.by_step["worker.md"].command == "claude"
    assert getattr(run.by_step.get("reviewer.md", run.provider), "grant",
                   None) is None


# the shipped flows


def shipped_reviewers():
    for name in ("build-feature", "code-review", "ops-check", "release-notes",
                 "repo-audit", "summarise-and-check", "weekly-digest"):
        fm = runner.config(name)
        for s in fm.steps:
            if s["role"] == "reviewer":
                yield name, fm, s


def test_every_shipped_reviewer_may_run_a_command():
    seen = list(shipped_reviewers())
    # build-feature runs two
    assert len(seen) == 8
    for name, _, s in seen:
        assert "shell" in (s.get("tools") or []), name


def test_the_shipped_reviewers_argv_carries_the_shell(fake_cli):
    cli_ = fake_cli(answer("VERDICT: ok\n"))
    for name, fm, s in shipped_reviewers():
        by_role = resolver.resolve(fm.raw, prompts.flow_path(name))
        run = engine.Run(name, fm, by_role)
        p = run.by_step[spec.step_id(s)]
        if not cli_provider.is_claude(p.command):
            continue
        argv, _ = p.argv("x")
        assert "Bash" in flag(argv, "--tools").split(","), name


# the provider check


def test_the_check_says_version_login_and_model(fake_cli, monkeypatch):
    monkeypatch.setattr(cli_provider.shutil, "which", lambda c: "/bin/claude")
    fake_cli()
    ok, detail = claude(model="m-1").check()
    assert ok
    assert "2.1.296" in detail and "claude.ai" in detail and "m-1" in detail


def test_the_check_fails_when_not_logged_in(fake_cli, monkeypatch):
    monkeypatch.setattr(cli_provider.shutil, "which", lambda c: "/bin/claude")
    cli_ = fake_cli()
    cli_.auth = (1, b'{"loggedIn": false, "authMethod": "none"}\n', b"")
    ok, detail = claude().check()
    assert not ok and "not logged in" in detail


def test_the_check_fails_below_the_floor(fake_cli, monkeypatch):
    monkeypatch.setattr(cli_provider.shutil, "which", lambda c: "/bin/claude")
    cli_ = fake_cli()
    cli_.version = (0, b"2.1.294 (Claude Code)\n", b"")
    ok, detail = claude().check()
    assert not ok and "2.1.295" in detail


def test_the_check_never_prints_the_account(fake_cli, monkeypatch):
    monkeypatch.setattr(cli_provider.shutil, "which", lambda c: "/bin/claude")
    cli_ = fake_cli()
    cli_.auth = (0, b'{"loggedIn": true, "authMethod": "claude.ai", '
                    b'"email": "someone@example.com"}\n', b"")
    ok, detail = claude().check()
    assert ok and "someone" not in detail


def test_the_check_of_another_command_spawns_nothing(fake_cli, monkeypatch):
    monkeypatch.setattr(cli_provider.shutil, "which", lambda c: "/bin/echo")
    cli_ = fake_cli()
    ok, _ = providers.build({"provider": "cli", "command": "echo"}).check()
    assert ok and cli_.asides == [] and cli_.calls == []


def test_the_provider_command_still_runs(capsys, monkeypatch):
    monkeypatch.setattr(cli_provider.shutil, "which", lambda c: None)
    assert cli.cmd_provider() == 0
