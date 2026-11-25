"""a model step's process gets what the cli needs to start and log in, and
none of the run's other secrets. these start a real child: what a process
inherits is only proven by a process."""
import json
import os
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
    return {k.upper(): v if v.startswith("decoy-") or not v else "set"
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


SWITCHES = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_MANTLE",
            "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
            "CLAUDE_CODE_USE_FOUNDRY")
SECRETS = ("GITHUB_TOKEN", "API_KEY", "AWS_ACCESS_KEY_ID",
           "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
           "AWS_BEARER_TOKEN_BEDROCK", "AZURE_CLIENT_SECRET",
           "AZURE_CLIENT_CERTIFICATE_PASSWORD", "GOOGLE_API_KEY")


@pytest.mark.parametrize("route", (None,) + SWITCHES)
def test_a_secret_the_run_holds_does_not_reach_the_model(child_env,
                                                         monkeypatch, route):
    if route:
        monkeypatch.setenv(route, "1")
    for name in SECRETS:
        monkeypatch.setenv(name, "decoy-" + name.lower())
    seen = child_env()
    for name in SECRETS:
        assert name not in seen, name
    assert (route in seen) is bool(route)


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


def test_two_connectors_never_see_each_other_s_credential(child_env, tmp_path,
                                                         monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "decoy-runner-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "decoy-runner-token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "decoy-oauth")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "decoy-bedrock")
    key = tmp_path / "keys" / "k.txt"
    key.parent.mkdir()
    key.write_text("decoy-file-key-for-tests\n", encoding="utf-8")
    api = child_env(auth="api-key", key_file=str(key))
    sub = child_env(auth="subscription")
    assert api["ANTHROPIC_API_KEY"] == "decoy-file-key-for-tests"
    assert "CLAUDE_CODE_PROMPT_CACHE_TTL" in api
    assert "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB" in api
    for gone in ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
                 "CLAUDE_CODE_USE_BEDROCK"):
        assert gone not in api
    for gone in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                 "CLAUDE_CODE_USE_BEDROCK"):
        assert gone not in sub
    assert "decoy-file-key-for-tests" not in json.dumps(sub)
    assert sub["CLAUDE_CODE_OAUTH_TOKEN"] == "decoy-oauth"


def test_a_listed_name_does_not_bring_a_stripped_credential_back(
        child_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "decoy-runner-key")
    seen = child_env(auth="subscription", env=["ANTHROPIC_API_KEY"])
    assert "ANTHROPIC_API_KEY" not in seen


SCRUB = "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"


def test_every_connector_s_cli_scrubs_its_own_children(child_env, tmp_path,
                                                       monkeypatch):
    monkeypatch.delenv(SCRUB, raising=False)
    key = tmp_path / "keys" / "k.txt"
    key.parent.mkdir()
    key.write_text("decoy-file-key-for-tests\n", encoding="utf-8")
    # the fake echoes "set" for a value with no decoy- prefix: the runner's 1
    assert child_env(connector="mine")[SCRUB] == "set"
    assert child_env(connector="sub", auth="subscription")[SCRUB] == "set"
    assert SCRUB not in child_env()
    assert SCRUB not in child_env(command="sometool", connector="mine")
    monkeypatch.setenv(SCRUB, "decoy-held")
    assert child_env(connector="mine")[SCRUB] == "decoy-held"
    assert child_env(connector="keyed", auth="api-key",
                     key_file=str(key))[SCRUB] == "set"


CAFE = "caf" + chr(0xE9)
# for each route, names that say where its login and region live, as the
# cli's own reference for that route names them
WHERE = {
    "CLAUDE_CODE_USE_BEDROCK": {
        "AWS_PROFILE": "decoy-" + CAFE, "AWS_REGION": "decoy-eu-west-2",
        "AWS_CONFIG_FILE": "decoy-" + os.path.join("aws", "config")},
    "CLAUDE_CODE_USE_MANTLE": {"AWS_PROFILE": "decoy-profile",
                               "AWS_DEFAULT_REGION": "decoy-us-east-1"},
    "CLAUDE_CODE_USE_ANTHROPIC_AWS": {
        "AWS_PROFILE": "decoy-profile",
        "AWS_SHARED_CREDENTIALS_FILE": "decoy-credentials"},
    "CLAUDE_CODE_USE_VERTEX": {
        "CLOUD_ML_REGION": "decoy-global",
        "VERTEX_REGION_CLAUDE_HAIKU_4_5": "decoy-us-east5",
        "GOOGLE_APPLICATION_CREDENTIALS": "decoy-adc.json"},
    "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD": {
        "GOOGLE_APPLICATION_CREDENTIALS": "decoy-adc.json",
        "CLOUDSDK_CONFIG": "decoy-gcloud"},
    "CLAUDE_CODE_USE_FOUNDRY": {
        "AZURE_TENANT_ID": "decoy-tenant",
        "AZURE_FEDERATED_TOKEN_FILE": "decoy-token-file"},
}


@pytest.mark.parametrize("switch", SWITCHES)
def test_a_cloud_route_keeps_the_names_that_say_where_its_login_lives(
        child_env, monkeypatch, switch):
    monkeypatch.setenv(switch, "1")
    for name, value in WHERE[switch].items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GITHUB_TOKEN", "decoy-github")
    seen = child_env()
    for name, value in WHERE[switch].items():
        assert seen.get(name) == value, name
    assert "GITHUB_TOKEN" not in seen


def test_no_cloud_route_no_cloud_names(child_env, monkeypatch):
    for names in WHERE.values():
        for name, value in names.items():
            monkeypatch.setenv(name, value)
    seen = child_env()
    for names in WHERE.values():
        for name in names:
            assert name not in seen, name


def test_each_route_keeps_its_own_names_only(child_env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
    monkeypatch.setenv("CLOUD_ML_REGION", "decoy-global")
    monkeypatch.setenv("AWS_PROFILE", "decoy-profile")
    monkeypatch.setenv("AZURE_TENANT_ID", "decoy-tenant")
    seen = child_env()
    assert seen["CLOUD_ML_REGION"] == "decoy-global"
    assert "AWS_PROFILE" not in seen and "AZURE_TENANT_ID" not in seen


def test_a_route_switch_is_read_as_the_cli_reads_it(child_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "decoy-profile")
    for on in ("1", " TRUE ", "yes", "On"):
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", on)
        assert child_env().get("AWS_PROFILE") == "decoy-profile", repr(on)
    for off in ("", " ", "0", "false", "2", "enabled"):
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", off)
        assert "AWS_PROFILE" not in child_env(), repr(off)


@pytest.mark.parametrize("switch", SWITCHES)
def test_a_connector_that_takes_the_route_away_takes_its_names_too(
        child_env, monkeypatch, switch):
    monkeypatch.setenv(switch, "1")
    for name, value in WHERE[switch].items():
        monkeypatch.setenv(name, value)
    sub = child_env(auth="subscription")
    assert switch not in sub
    for name in WHERE[switch]:
        assert name not in sub, name


def test_the_route_names_are_claude_s_not_another_command_s(child_env,
                                                           monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_PROFILE", "decoy-profile")
    assert "AWS_PROFILE" not in child_env(command="sometool")


def a_settings_file(tmp_path, monkeypatch, said):
    path = tmp_path / "settings.json"
    path.write_text(said if isinstance(said, str) else json.dumps(said),
                    encoding="utf-8")
    monkeypatch.setattr(cli_provider, "USER_SETTINGS", path)


def test_a_route_set_up_only_in_the_settings_file_reaches_every_step(
        child_env, tmp_path, monkeypatch):
    a_settings_file(tmp_path, monkeypatch, {"env": {
        "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_PROFILE": "decoy-" + CAFE,
        "AWS_REGION": "decoy-eu-west-2", "SOMETHING_ELSE": "decoy-else",
        "AWS_BEARER_TOKEN_BEDROCK": "decoy-bedrock-key",
        "AWS_SECRET_ACCESS_KEY": "decoy-aws"}})
    seen = child_env()
    assert seen["CLAUDE_CODE_USE_BEDROCK"] == "set"
    assert seen["AWS_PROFILE"] == "decoy-" + CAFE
    assert seen["AWS_REGION"] == "decoy-eu-west-2"
    for name in ("SOMETHING_ELSE", "AWS_BEARER_TOKEN_BEDROCK",
                 "AWS_SECRET_ACCESS_KEY"):
        assert name not in seen, name


def test_the_settings_file_s_route_names_win_over_the_shell_s(
        child_env, tmp_path, monkeypatch):
    # the cli writes its settings file's env block over the shell's values,
    # so a step that reads no file gets what one that reads it would
    a_settings_file(tmp_path, monkeypatch, {"env": {
        "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_PROFILE": "decoy-file"}})
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_PROFILE", "decoy-shell")
    monkeypatch.setenv("AWS_REGION", "decoy-shell-region")
    seen = child_env()
    assert seen["AWS_PROFILE"] == "decoy-file"
    assert seen["AWS_REGION"] == "decoy-shell-region"


def test_a_settings_file_that_empties_a_route_s_switch_turns_it_off(
        child_env, tmp_path, monkeypatch):
    a_settings_file(tmp_path, monkeypatch, {"env": {
        "CLAUDE_CODE_USE_BEDROCK": ""}})
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_PROFILE", "decoy-shell")
    seen = child_env()
    assert seen["CLAUDE_CODE_USE_BEDROCK"] == ""
    assert "AWS_PROFILE" not in seen


def test_a_settings_file_that_switches_no_route_hands_nothing(
        child_env, tmp_path, monkeypatch):
    for said, switch in (
            ({"env": {"AWS_PROFILE": "decoy-profile"}}, None),
            ({"env": {"CLAUDE_CODE_USE_BEDROCK": 1,
                      "AWS_PROFILE": "decoy-profile"}}, None),
            ({"env": {"CLAUDE_CODE_USE_BEDROCK": "decoy-0",
                      "AWS_PROFILE": "decoy-profile"}}, "decoy-0"),
            ({"env": ["CLAUDE_CODE_USE_BEDROCK"]}, None),
            ({"env": None}, None), ("not json {", None)):
        a_settings_file(tmp_path, monkeypatch, said)
        seen = child_env()
        assert "AWS_PROFILE" not in seen, said
        assert seen.get("CLAUDE_CODE_USE_BEDROCK") == switch, said


def test_a_connector_off_the_route_takes_none_of_the_settings_route(
        child_env, tmp_path, monkeypatch):
    a_settings_file(tmp_path, monkeypatch, {"env": {
        "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_PROFILE": "decoy-profile"}})
    sub = child_env(auth="subscription")
    assert "CLAUDE_CODE_USE_BEDROCK" not in sub
    assert "AWS_PROFILE" not in sub


def test_the_operator_lists_names_for_every_step_outside_the_flow(
        child_env, monkeypatch):
    monkeypatch.setenv("AGENTWEFT_PROVIDER_ENV", "route_a, ROUTE_B,,  ")
    monkeypatch.setenv("ROUTE_A", "decoy-a")
    monkeypatch.setenv("ROUTE_B", "decoy-b")
    monkeypatch.setenv("GITHUB_TOKEN", "decoy-github")
    seen = child_env()
    assert seen["ROUTE_A"] == "decoy-a" and seen["ROUTE_B"] == "decoy-b"
    assert "GITHUB_TOKEN" not in seen
    assert "AGENTWEFT_PROVIDER_ENV" not in seen


def test_an_operator_listed_secret_reaches_a_route_that_needs_it(
        child_env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "decoy-bedrock-key")
    assert "AWS_BEARER_TOKEN_BEDROCK" not in child_env()
    monkeypatch.setenv("AGENTWEFT_PROVIDER_ENV", "AWS_BEARER_TOKEN_BEDROCK")
    assert child_env()["AWS_BEARER_TOKEN_BEDROCK"] == "decoy-bedrock-key"


@pytest.mark.parametrize("listed", ["ANTHROPIC_API_KEY",
                                    "CLAUDE_CODE_USE_BEDROCK,AWS_PROFILE"])
def test_an_operator_listed_name_does_not_bring_a_stripped_credential_back(
        child_env, monkeypatch, listed):
    monkeypatch.setenv("AGENTWEFT_PROVIDER_ENV", listed)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "decoy-runner-key")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_PROFILE", "decoy-profile")
    sub = child_env(auth="subscription")
    for name in listed.split(","):
        assert name not in sub, name


def test_one_name_given_alone_is_one_name(child_env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "decoy-profile")
    monkeypatch.setenv("A", "decoy-letter")
    seen = child_env(env="AWS_PROFILE")
    assert seen["AWS_PROFILE"] == "decoy-profile"
    assert "A" not in seen
