"""a model step's process gets what the cli needs to start and log in, and
none of the run's other secrets. these start a real child: what a process
inherits is only proven by a process."""
import json
import subprocess
import sys
import types

import pytest

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.providers import cli_provider

SAYS_ITS_ENV = r"""
import json, os, sys


def said():
    # only a value a test set is echoed back, never one this machine holds
    return {k.upper(): v if v.startswith("decoy-") else "set"
            for k, v in os.environ.items()}


if "-p" in sys.argv and "--output-format" in sys.argv:
    sys.stdin.buffer.read()
    sys.stdout.write(json.dumps({"type": "result", "is_error": False,
                                 "result": json.dumps(said())}))
else:
    sys.stdout.write(json.dumps(said()))
"""


@pytest.fixture
def child_env(tmp_path, monkeypatch):
    """-> a function asking a fake cli for the environment it was started
    with, as {NAME: value}."""
    script = tmp_path / "fake_cli.py"
    script.write_text(SAYS_ITS_ENV, encoding="utf-8")

    def real(argv):
        return [sys.executable, str(script)] + list(argv[1:])

    monkeypatch.setattr(cli_provider, "subprocess", types.SimpleNamespace(
        run=lambda argv, **kw: subprocess.run(real(argv), **kw),
        Popen=lambda argv, **kw: subprocess.Popen(real(argv), **kw),
        TimeoutExpired=subprocess.TimeoutExpired))

    def ask(command="claude", **opts):
        p = providers.build(dict(opts, provider="cli", command=command))
        r = p.ask("go", timeout=60)
        assert r.text, r.detail
        return json.loads(r.text)
    return ask


def test_a_secret_the_run_holds_does_not_reach_the_model(child_env,
                                                         monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "decoy-github")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "decoy-aws")
    monkeypatch.setenv("API_KEY", "decoy-api")
    seen = child_env()
    assert "GITHUB_TOKEN" not in seen
    assert "AWS_SECRET_ACCESS_KEY" not in seen
    assert "API_KEY" not in seen


def test_the_cli_keeps_what_it_starts_and_logs_in_with(child_env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "decoy-oauth")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "decoy-anthropic")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "decoy-config")
    seen = child_env()
    assert seen["CLAUDE_CODE_OAUTH_TOKEN"] == "decoy-oauth"
    assert seen["ANTHROPIC_API_KEY"] == "decoy-anthropic"
    assert seen["CLAUDE_CONFIG_DIR"] == "decoy-config"
    assert seen.get("PATH")


def test_another_command_does_not_get_claude_s_login(child_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "decoy-anthropic")
    seen = child_env(command="sometool")
    assert "ANTHROPIC_API_KEY" not in seen
    assert seen.get("PATH")


def test_a_name_the_provider_lists_is_passed_through(child_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "decoy-profile")
    monkeypatch.setenv("GITHUB_TOKEN", "decoy-github")
    seen = child_env(env=["aws_profile"])
    assert seen["AWS_PROFILE"] == "decoy-profile"
    assert "GITHUB_TOKEN" not in seen


def test_one_name_given_alone_is_one_name(child_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "decoy-profile")
    monkeypatch.setenv("A", "decoy-letter")
    seen = child_env(env="AWS_PROFILE")
    assert seen["AWS_PROFILE"] == "decoy-profile"
    assert "A" not in seen
