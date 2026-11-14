"""named connectors: a provider block declared once and picked by name on a
step, beside its model, each started with its own credential and no other."""
import json
import sys
import types

import pytest

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.orchestrate import project, workflow
from agentweft.providers import api_provider
from agentweft.runner import engine, prompts, resume, spend, state, stops

KEY = "decoy-key-for-tests-0001"
CLAUDE = "provider:\n  provider: cli\n  command: claude\n  model: m-small\n"


def answer(text):
    return (0, json.dumps({"type": "result", "is_error": False, "result": text,
                           "session_id": "s-1", "total_cost_usd": 0.25,
                           "usage": {"input_tokens": 10, "output_tokens": 4},
                           "modelUsage": {"m-small-1": {}}}).encode("utf-8"),
            b"")


def key_file(tmp_path, text=KEY, name="aw-key.txt"):
    outside = tmp_path / "keys"
    outside.mkdir(exist_ok=True)
    path = outside / name
    path.write_text(text, encoding="utf-8")
    return path


def a_flow(tmp_path, monkeypatch, steps, tail=CLAUDE, project_yml=None):
    place = tmp_path / "place"
    place.mkdir()
    home = tmp_path / "orchestrate"
    home.mkdir()
    monkeypatch.setattr(workflow, "ROOT", [str(home)])
    if project_yml is not None:
        (home / "project.yml").write_text(project_yml, encoding="utf-8")
    d = tmp_path / "flows" / "two"
    d.mkdir(parents=True)
    body = "name: two\nworkdir: " + json.dumps(str(place)) + "\nsteps:\n"
    for role, more in steps:
        body += "  - role: " + role + "\n    prompt: " + role + ".md\n"
        for line in more:
            body += "    " + line + "\n"
        (d / (role + ".md")).write_text("# " + role + "\n\ndo it.\n",
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body + tail, encoding="utf-8")
    (d / "instructions.md").write_text("the two flow.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", "two", "--force"])
    monkeypatch.setattr(resume, "JOURNAL", None)
    return place


def declared_key(path):
    return ("connectors:\n  claude-api:\n    key_file: "
            + json.dumps(str(path)) + "\n")


def test_the_built_ins_need_no_declaring():
    sub = providers.build("claude-sub")
    stub = providers.build("stub")
    assert (sub.name, sub.connector, sub.auth) == ("cli", "claude-sub",
                                                   "subscription")
    assert (stub.name, stub.connector) == ("fake", "stub")
    api = providers.build("claude-api")
    assert (api.name, api.connector, api.auth) == ("cli", "claude-api",
                                                   "api-key")


def test_an_inline_block_keeps_its_meaning_and_says_inherit():
    p = providers.build({"provider": "cli", "command": "claude"})
    assert (p.name, p.connector, p.auth) == ("cli", None, "inherit")


def test_a_declared_block_merges_over_the_built_in(tmp_path):
    path = key_file(tmp_path)
    p = providers.build("claude-api", connectors={
        "claude-api": {"key_file": str(path), "max_turns": 7}})
    assert p.key_file == str(path)
    assert p.turns == 7
    assert p.refuses() == ""


@pytest.mark.parametrize("block, said", [
    ({"provider": "cli", "auth": "token"}, "auth should be one of"),
    ({"provider": "nope"}, "provider should be one of"),
    ({"provider": "fake", "auth": "api-key"}, "fake answers without a login"),
    ({"provider": "api", "auth": "subscription"},
     "the api provider has no subscription login"),
    ({"provider": "cli", "auth": "api-key", "key_file": "keys/k.txt"},
     "key_file should be a full path"),
    ({"provider": "cli", "key_file": 7}, "key_file should be a full path"),
    ({"provider": "cli", "auth": "api-key", "command": "python"},
     "hands its key to claude only, never to python"),
    ({"provider": "cli", "auth": "api-key", "command": "bin\\py.exe"},
     "hands its key to claude only"),
    ("cli", "should be a mapping"),
])
def test_a_wrong_block_is_refused_with_its_reason(block, said):
    bad = providers.connectors.check({"mine": block})
    assert len(bad) == 1 and said in bad[0] and bad[0].startswith("mine: ")


def test_a_connector_named_after_a_provider_kind_is_refused():
    [bad] = providers.connectors.check({"cli": {"provider": "cli"}})
    assert "is a provider's own name" in bad


def test_an_unknown_name_says_which_there_are():
    with pytest.raises(ValueError) as e:
        providers.build("claude-apo")
    assert "claude-apo names no connector" in str(e.value)
    assert "claude-api, claude-sub, stub" in str(e.value)


def test_a_missing_key_file_refuses_the_step_before_any_call(tmp_path,
                                                             fake_cli):
    cli = fake_cli(answer("done\n"))
    gone = tmp_path / "keys" / "none.txt"
    p = providers.build("claude-api", connectors={
        "claude-api": {"key_file": str(gone)}})
    why = p.refuses()
    assert why.startswith("claude-api reads its key from ")
    assert "which is not there" in why
    r = p.ask("go", timeout=5)
    assert not r and r.retryable is False and r.detail == why
    assert cli.calls == []


def test_an_empty_key_file_refuses_the_step(tmp_path, fake_cli):
    cli = fake_cli(answer("done\n"))
    p = providers.build("claude-api", connectors={
        "claude-api": {"key_file": str(key_file(tmp_path, " \n"))}})
    assert "is empty" in p.refuses()
    assert not p.ask("go", timeout=5) and cli.calls == []


def test_api_key_with_no_key_file_refuses(fake_cli):
    fake_cli(answer("done\n"))
    p = providers.build("claude-api")
    assert p.refuses() == ("claude-api has auth: api-key and no key file:"
                           " set AGENTWEFT_KEY_FILE in your environment, or"
                           " key_file on the connector in your flow")


def test_a_key_file_inside_the_place_is_refused(tmp_path, fake_cli):
    fake_cli(answer("done\n"))
    place = tmp_path / "place"
    place.mkdir()
    (place / "k.txt").write_text(KEY, encoding="utf-8")
    p = providers.build("claude-api", where=place, connectors={
        "claude-api": {"key_file": str(place / "k.txt")}})
    assert "inside the place" in p.refuses()


def test_a_key_written_after_the_check_is_read_at_call_time(tmp_path,
                                                            fake_cli):
    cli = fake_cli(answer("done\n"))
    path = key_file(tmp_path, "decoy-first-key-for-tests")
    p = providers.build("claude-api", connectors={
        "claude-api": {"key_file": str(path)}})
    assert p.refuses() == ""
    path.write_text("decoy-second-key-for-tests", encoding="utf-8")
    assert p.ask("go", timeout=5)
    assert cli.calls[0]["kw"]["env"]["ANTHROPIC_API_KEY"] == \
        "decoy-second-key-for-tests"


def test_the_key_is_never_on_the_command_line(tmp_path, fake_cli):
    cli = fake_cli(answer("done\n"))
    p = providers.build("claude-api", connectors={
        "claude-api": {"key_file": str(key_file(tmp_path))}})
    assert p.ask("go", timeout=5)
    assert KEY not in json.dumps(cli.calls[0]["argv"])
    assert KEY not in (cli.calls[0]["stdin"] or b"").decode("utf-8")


def test_the_api_provider_reads_its_key_from_the_file(tmp_path, monkeypatch):
    sent = []

    def post(url, json=None, timeout=None, headers=None):
        sent.append(headers)
        return types.SimpleNamespace(status_code=200, json=lambda: {
            "content": [{"type": "text", "text": "ok"}], "usage": {}})

    monkeypatch.setattr(api_provider.httpx, "post", post)
    monkeypatch.setenv("API_KEY", "decoy-from-the-environment")
    p = providers.build({"provider": "api", "model": "m", "url": "http://x",
                         "auth": "api-key",
                         "key_file": str(key_file(tmp_path))})
    assert p.ask("go", timeout=5).text == "ok"
    assert sent[0]["x-api-key"] == KEY


def test_the_api_provider_refuses_on_a_missing_key_file(tmp_path,
                                                        monkeypatch):
    monkeypatch.setattr(api_provider.httpx, "post", lambda *a, **k: 1 / 0)
    p = providers.build({"provider": "api", "model": "m", "url": "http://x",
                         "auth": "api-key",
                         "key_file": str(tmp_path / "none.txt")})
    r = p.ask("go", timeout=5)
    assert not r and r.retryable is False and "which is not there" in r.detail


def test_project_yml_declares_connectors_and_the_flow_wins(tmp_path):
    held = project.Held(tmp_path / "project.yml",
                        "project:\n  name: here\nconnectors:\n  cheap:\n"
                        "    provider: cli\n    model: m-cheap\n"
                        "  own:\n    provider: cli\n    auth: subscription\n")
    got = providers.connectors.declared({"connectors": {
        "cheap": {"model": "m-flow"}}}, held)
    assert got["cheap"] == {"provider": "cli", "model": "m-flow"}
    assert got["own"] == {"provider": "cli", "auth": "subscription"}


@pytest.mark.parametrize("block, said", [
    ({"provider": "cli", "auth": "api-key"}, "auth: api-key"),
    ({"provider": "cli", "auth": "subscription",
      "key_file": "~/.ssh/id_any"}, "key_file"),
    ({"provider": "cli", "command": "/opt/tools/claude"}, "command"),
    ({"provider": "api", "url": "https://elsewhere.example"}, "url"),
    ({"provider": "cli", "env": ["AWS_SECRET_ACCESS_KEY"]}, "env"),
])
def test_project_yml_may_not_say_where_a_credential_comes_from_or_goes(
        block, said):
    raw = {"project": {"name": "here"}, "connectors": {"mine": block}}
    [bad] = project.check(raw)
    assert bad == ("connectors: mine: " + said + " is the person's to set,"
                   " in the flow or their own environment, never in the"
                   " project's file")
    with pytest.raises(ValueError) as e:
        project.load(raw)
    assert str(e.value).startswith("project.yml: connectors: mine: ")
    assert providers.connectors.check({"mine": block}) == []


@pytest.mark.parametrize("block", [
    {"provider": "cli", "model": "m-cheap"},
    {"provider": "cli", "auth": "subscription", "max_turns": 9},
    {"provider": "cli", "auth": "inherit"},
    {"provider": "fake"},
])
def test_project_yml_may_name_connectors_and_their_models(block):
    assert project.check({"project": {"name": "here"},
                          "connectors": {"mine": block}}) == []


def test_a_bad_connectors_block_in_project_yml_is_refused():
    bad = project.check({"project": {"name": "here"},
                         "connectors": {"x": {"provider": "cli",
                                              "auth": "token"}}})
    assert bad == ["connectors: x: auth should be one of subscription,"
                   " api-key, inherit"]


@pytest.mark.parametrize("name", ["claude-api", "claude-sub"])
def test_a_built_in_s_command_cannot_be_declared_again(tmp_path, name):
    declared = {name: {"key_file": str(key_file(tmp_path)),
                       "command": "python"}}
    [bad] = providers.connectors.check(declared)
    assert bad == (name + ": is a built-in connector, which starts claude;"
                   " its command is not declared again: declare a connector"
                   " of another name")
    with pytest.raises(ValueError) as e:
        providers.build(name, where=tmp_path, connectors=declared)
    assert "its command is not declared again" in str(e.value)
    with pytest.raises(ValueError):
        providers.build({"provider": name, "command": "python"},
                        connectors=declared)


def test_a_command_inside_the_place_is_handed_no_credential(tmp_path,
                                                            fake_cli):
    fake_cli(answer("done\n"))
    place = tmp_path / "place"
    (place / "tools").mkdir(parents=True)
    path = str(key_file(tmp_path))
    for command in ("tools/claude", "./claude.cmd",
                    str(place / "tools" / "claude"),
                    str(place / "tools" / "claude").replace("/", "\\")):
        p = providers.build({"provider": "cli", "auth": "api-key",
                             "key_file": path, "command": command},
                            where=place)
        assert "inside the place" in p.refuses(), command
        with pytest.raises(providers.connectors.NoKey):
            p.child_env()
        sub = providers.build({"provider": "cli", "auth": "subscription",
                               "command": command}, where=place)
        assert "inside the place" in sub.refuses(), command
        with pytest.raises(providers.connectors.NoKey):
            sub.child_env()
    outside = tmp_path / "bin" / "claude.exe"
    p = providers.build({"provider": "cli", "auth": "api-key",
                         "key_file": path, "command": str(outside)},
                        where=place)
    assert p.refuses() == ""
    assert p.child_env()["ANTHROPIC_API_KEY"] == KEY


def test_a_claude_in_a_run_s_folder_is_handed_no_credential(tmp_path,
                                                           fake_cli):
    fake_cli(answer("done\n"))
    place = tmp_path / "place"
    place.mkdir()
    written = state.RUNS / "earlier-run" / "tmp" / "claude.cmd"
    written.parent.mkdir(parents=True)
    written.write_text("@echo off\n", encoding="utf-8")
    path = str(key_file(tmp_path))
    for command in (str(written), str(written).replace("/", "\\")):
        for block in ({"provider": "cli", "auth": "api-key", "key_file": path,
                       "command": command},
                      {"provider": "cli", "auth": "subscription",
                       "command": command}):
            p = providers.build(block, where=place)
            assert p.refuses() == (
                "cli starts " + command + ", in agentweft's"
                " runs folder, where a step can write it: a credential goes"
                " only to a claude outside the place and the runs folder")
            with pytest.raises(providers.connectors.NoKey):
                p.child_env()
    inherit = providers.build({"provider": "cli", "command": str(written)},
                              where=place)
    assert inherit.refuses() == "" and inherit.command_path is None


def test_a_bare_claude_is_found_once_and_judged_where_it_lies(tmp_path,
                                                              monkeypatch,
                                                              fake_cli):
    cli = fake_cli(answer("done\n"))
    place = tmp_path / "place"
    place.mkdir()
    found = []
    monkeypatch.setattr(providers.connectors.shutil, "which",
                        lambda command: found.append(command) or lies[0])
    path = str(key_file(tmp_path))
    for where, said in ((place / "node_modules" / ".bin" / "claude.exe",
                         "inside the place"),
                        (state.RUNS / "r-1" / "tmp" / "claude",
                         "in agentweft's runs folder")):
        lies = [str(where)]
        p = providers.build("claude-api", where=place, connectors={
            "claude-api": {"key_file": path}})
        assert said in p.refuses()
        assert str(where) in p.refuses()
        assert not p.ask("go", timeout=5) and cli.calls == []
    lies = [str(tmp_path / "bin" / "claude.exe")]
    found.clear()
    p = providers.build("claude-api", where=place, connectors={
        "claude-api": {"key_file": path}})
    assert p.refuses() == "" and p.ask("go", timeout=5)
    assert p.ask("go", timeout=5) and found == ["claude"]
    assert p.command_path == str((tmp_path / "bin" / "claude.exe").resolve())
    lies = [None]
    nowhere = providers.build("claude-sub", where=place)
    assert nowhere.refuses() == "" and nowhere.command_path is None


def test_the_step_line_says_which_claude_it_started(tmp_path, monkeypatch,
                                                    fake_cli):
    outside = tmp_path / "bin" / "claude.exe"
    monkeypatch.setattr(providers.connectors.shutil, "which",
                        lambda command: str(outside))
    two_connectors(tmp_path, monkeypatch, fake_cli, third="plain")
    with open(tmp_path / "flows" / "two" / "flow.yaml", "a",
              encoding="utf-8") as f:
        f.write("  plain:\n    provider: cli\n")
    assert engine.main() == 0
    api, sub, plain = lines()
    assert api["command_path"] == sub["command_path"] == str(
        outside.resolve())
    assert plain["auth"] == "inherit" and "command_path" not in plain


def test_project_yml_redeclaring_a_built_in_s_command_gets_no_key(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, [("worker", ["provider: claude-api"])],
           project_yml="project:\n  name: here\nconnectors:\n  claude-api:\n"
           "    key_file: " + json.dumps(str(key_file(tmp_path))) + "\n"
           "    command: python\n")
    cli = fake_cli(answer("done\n"))
    assert engine.main() != 0
    assert not [c for c in cli.calls + [{"kw": kw} for kw in cli.aside_kw]
                if KEY in json.dumps(c["kw"].get("env") or {})]
    assert cli.calls == []


def test_a_step_names_a_connector_and_each_gets_its_own_credential(
        tmp_path, monkeypatch, fake_cli):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "decoy-runner-key")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "decoy-oauth")
    path = key_file(tmp_path)
    a_flow(tmp_path, monkeypatch,
           [("worker", ["provider: claude-api"]),
            ("reviewer", ["provider: claude-sub"])],
           tail=CLAUDE + declared_key(path))
    cli = fake_cli(answer("done\n"), answer("VERDICT: ok\n\nfine\n"))
    assert engine.main() == 0
    api, sub = (c["kw"]["env"] for c in cli.calls)
    assert api["ANTHROPIC_API_KEY"] == KEY
    assert api["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "1h"
    assert api["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in api
    assert "ANTHROPIC_API_KEY" not in sub
    assert sub["CLAUDE_CODE_OAUTH_TOKEN"] == "decoy-oauth"
    for path in state.RUNS.rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text(encoding="utf-8",
                                             errors="replace"), path


def test_a_key_of_any_shape_the_model_echoes_is_in_no_run_file(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, [("worker", ["provider: claude-api"])],
           tail=CLAUDE + declared_key(key_file(tmp_path)))
    cli = fake_cli(answer("my environment says " + KEY + "\n"))
    assert engine.main() == 0
    assert len(cli.calls) == 1
    written = [p for p in state.RUNS.rglob("*") if p.is_file()]
    seen = "".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in written)
    assert "my environment says sk-ant-REDACTED" in seen
    assert KEY not in seen


def test_a_step_naming_no_connector_there_is_stops_the_run(tmp_path,
                                                          monkeypatch,
                                                          fake_cli, capsys):
    a_flow(tmp_path, monkeypatch, [("worker", ["provider: claude-apo"])])
    cli = fake_cli(answer("done\n"))
    assert engine.main() == 1
    assert "claude-apo names no connector" in capsys.readouterr().out
    assert cli.calls == []


def test_a_step_on_a_missing_key_file_is_refused_before_its_call(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, [("worker", ["provider: claude-api"])],
           tail=CLAUDE + declared_key(tmp_path / "keys" / "none.txt"))
    cli = fake_cli(answer("done\n"))
    assert engine.main() != 0
    assert cli.calls == []
    [line] = [json.loads(l) for p in state.RUNS.rglob("steps.jsonl")
              for l in p.read_text(encoding="utf-8").split("\n") if l]
    assert "which is not there" in line["why"]


def test_project_yml_connectors_reach_the_step(tmp_path, monkeypatch,
                                               fake_cli):
    a_flow(tmp_path, monkeypatch, [("worker", ["provider: cheap"])],
           project_yml="project:\n  name: here\nconnectors:\n  cheap:\n"
           "    provider: cli\n    auth: subscription\n    model: m-cheap\n")
    cli = fake_cli(answer("done\n"))
    assert engine.main() == 0
    argv = cli.calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == "m-cheap"
    assert "ANTHROPIC_API_KEY" not in cli.calls[0]["kw"]["env"]


def test_a_key_file_project_yml_names_is_never_read(tmp_path, monkeypatch,
                                                     fake_cli, capsys):
    secret = tmp_path / "home" / ".ssh" / "id_any"
    secret.parent.mkdir(parents=True)
    secret.write_text("not-a-provider-key-but-private\n", encoding="utf-8")
    a_flow(tmp_path, monkeypatch, [("worker", ["provider: mine"])],
           project_yml="project:\n  name: here\nconnectors:\n  mine:\n"
           "    provider: cli\n    auth: api-key\n    key_file: "
           + json.dumps(str(secret)) + "\n")
    cli = fake_cli(answer("done\n"))
    assert engine.main() != 0
    assert "project.yml: connectors: mine: auth: api-key is the person's" \
        in capsys.readouterr().out
    assert cli.calls == [] and cli.asides == []
    for path in state.RUNS.rglob("*"):
        if path.is_file():
            assert "not-a-provider-key" not in path.read_text(
                encoding="utf-8", errors="replace"), path


def test_the_person_s_environment_names_the_key_file(tmp_path, monkeypatch,
                                                      fake_cli):
    cli = fake_cli(answer("done\n"))
    monkeypatch.setenv("AGENTWEFT_KEY_FILE", str(key_file(tmp_path)))
    p = providers.build("claude-api", where=tmp_path / "place")
    assert p.refuses() == ""
    assert p.ask("go", timeout=5)
    assert cli.calls[0]["kw"]["env"]["ANTHROPIC_API_KEY"] == KEY
    other = key_file(tmp_path, "decoy-flow-key-for-tests-02", name="f.txt")
    p = providers.build("claude-api", connectors={
        "claude-api": {"key_file": str(other)}})
    assert p.child_env()["ANTHROPIC_API_KEY"] == "decoy-flow-key-for-tests-02"
    monkeypatch.setenv("AGENTWEFT_KEY_FILE", "keys/k.txt")
    assert providers.build("claude-api").refuses() == (
        "claude-api reads its key from AGENTWEFT_KEY_FILE, which should be a"
        " full path (or start with ~), not 'keys/k.txt'")


def test_a_key_file_named_by_a_dot_env_inside_the_place_is_refused(
        tmp_path, monkeypatch, fake_cli):
    fake_cli(answer("done\n"))
    path = key_file(tmp_path)
    place = tmp_path / "place"
    place.mkdir()
    (place / ".env").write_text("AGENTWEFT_KEY_FILE=" + str(path) + "\n",
                                encoding="utf-8")
    monkeypatch.delenv("AGENTWEFT_KEY_FILE", raising=False)
    monkeypatch.chdir(place)
    engine.load_env()
    p = providers.build("claude-api", where=place)
    assert p.refuses() == (
        "claude-api reads its key from AGENTWEFT_KEY_FILE, which "
        + str((place / ".env").resolve()) + " sets, inside the place: that"
        " file is the project's. set it in your own environment, or in a"
        " .env outside the place")
    with pytest.raises(providers.connectors.NoKey):
        p.child_env()
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / ".env").write_text("AGENTWEFT_KEY_FILE=" + str(path) + "\n",
                               encoding="utf-8")
    monkeypatch.chdir(mine)
    engine.load_env()
    assert providers.build("claude-api", where=place).refuses() == ""


def pinned(cli):
    argv = cli.calls[-1]["argv"]
    said = json.loads(argv[argv.index("--settings") + 1])
    return (said.get("env") or {}).get("ANTHROPIC_BASE_URL")


@pytest.mark.parametrize("connector", ["claude-api", "claude-sub"])
def test_a_grant_less_call_with_a_credential_pins_where_it_is_sent(
        tmp_path, monkeypatch, fake_cli, connector):
    cli = fake_cli(answer("done\n"))
    monkeypatch.setenv("AGENTWEFT_KEY_FILE", str(key_file(tmp_path)))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    place = tmp_path / "place"
    assert providers.build(connector, where=place).ask("go", timeout=5)
    assert pinned(cli) == providers.cli_provider.DEFAULT_BASE_URL
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example/v1")
    assert providers.build(connector, where=place).ask("go", timeout=5)
    assert pinned(cli) == "https://gateway.example/v1"
    own = tmp_path / "own-settings.json"
    own.write_text(json.dumps({"env": {
        "ANTHROPIC_BASE_URL": "https://mine.example"}}), encoding="utf-8")
    monkeypatch.setattr(providers.cli_provider, "USER_SETTINGS", str(own))
    assert providers.build(connector, where=place).ask("go", timeout=5)
    assert pinned(cli) == "https://mine.example"
    monkeypatch.setattr(providers.cli_provider, "USER_SETTINGS", "none.json")
    place.mkdir(exist_ok=True)
    (place / ".env").write_text("ANTHROPIC_BASE_URL=https://theirs.example\n",
                                encoding="utf-8")
    monkeypatch.chdir(place)
    engine.load_env()
    assert providers.build(connector, where=place).ask("go", timeout=5)
    assert pinned(cli) == providers.cli_provider.DEFAULT_BASE_URL


def test_a_call_with_no_credential_or_a_grant_pins_nothing(tmp_path,
                                                           monkeypatch,
                                                           fake_cli):
    cli = fake_cli(answer("done\n"))
    monkeypatch.setenv("AGENTWEFT_KEY_FILE", str(key_file(tmp_path)))
    for block, grant in (({"provider": "cli"}, None),
                         ("claude-api", ["read", "edit"]),
                         ("claude-sub", ["read"])):
        assert providers.build(block, where=tmp_path / "place",
                               grant=grant).ask("go", timeout=5)
        assert pinned(cli) is None, block


def lines():
    return [json.loads(l) for p in state.RUNS.rglob("steps.jsonl")
            for l in p.read_text(encoding="utf-8").split("\n") if l]


def two_connectors(tmp_path, monkeypatch, fake_cli, third=None):
    steps = [("worker", ["provider: claude-api"]),
             ("reviewer", ["provider: claude-sub"])]
    if third:
        steps.append(("closer", ["provider: " + third]))
    place = a_flow(tmp_path, monkeypatch, steps,
                   tail=CLAUDE + declared_key(key_file(tmp_path)))
    cli = fake_cli(answer("done\n"), answer("VERDICT: ok\n\nfine\n"),
                   answer("closed\n"))
    cli.auth = lambda kw: (0, json.dumps({
        "loggedIn": True, "email": "someone@example.com",
        "authMethod": "api_key" if "ANTHROPIC_API_KEY" in kw["env"]
        else "claude.ai"}).encode("utf-8"), b"")
    return place, cli


def test_every_step_line_says_its_connector_and_auth(tmp_path, monkeypatch,
                                                     fake_cli):
    two_connectors(tmp_path, monkeypatch, fake_cli)
    assert engine.main() == 0
    api, sub = lines()
    assert (api["connector"], api["auth"], api["auth_method"]) == (
        "claude-api", "api-key", "api_key")
    assert (sub["connector"], sub["auth"], sub["auth_method"]) == (
        "claude-sub", "subscription", "claude.ai")
    text = "".join(p.read_text(encoding="utf-8")
                   for p in state.RUNS.rglob("*") if p.is_file())
    assert "someone@example.com" not in text


def test_an_inline_block_s_line_says_inherit_and_reads_no_auth(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, [("worker", [])])
    cli = fake_cli(answer("done\n"))
    assert engine.main() == 0
    [line] = lines()
    assert (line["connector"], line["auth"]) == (None, "inherit")
    assert "auth_method" not in line
    assert not [a for a in cli.asides if a[1:3] == ["auth", "status"]]


def test_the_cli_s_auth_is_read_once_per_connector_in_the_place(
        tmp_path, monkeypatch, fake_cli):
    place, cli = two_connectors(tmp_path, monkeypatch, fake_cli,
                                third="claude-api")
    assert engine.main() == 0
    asked = [(a, kw) for a, kw in zip(cli.asides, cli.aside_kw)
             if a[1:3] == ["auth", "status"]]
    assert len(asked) == 2
    assert all(a == ["claude", "auth", "status", "--json"] for a, _ in asked)
    assert all(kw["cwd"] == str(place) for _, kw in asked)
    api_env = [kw["env"] for a, kw in asked]
    assert sorted("ANTHROPIC_API_KEY" in env for env in api_env) == [False,
                                                                     True]
    assert lines()[2]["auth_method"] == "api_key"


@pytest.mark.parametrize("said", [
    (0, b"not json\n", b""),
    (0, b'{"loggedIn": true}\n', b""),
    (1, b'{"loggedIn": false, "authMethod": "none"}\n', b""),
    (0, b"", b""),
])
def test_an_unreadable_auth_status_refuses_the_step_before_its_call(
        tmp_path, monkeypatch, fake_cli, said):
    place, cli = two_connectors(tmp_path, monkeypatch, fake_cli)
    cli.auth = said
    assert engine.main() != 0
    assert cli.calls == []
    [api] = lines()
    assert "auth_method" not in api and api["auth"] == "api-key"
    assert api["why"].startswith("claude-api has auth: api-key, and `claude"
                                 " auth status` says it logs in with nothing"
                                 " it could read")


def a_step_on(tmp_path, monkeypatch, fake_cli, connector, method,
              more=""):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    a_flow(tmp_path, monkeypatch, [("worker", ["provider: " + connector])],
           tail=CLAUDE + declared_key(key_file(tmp_path)) + more)
    cli = fake_cli(answer("done\n"))
    cli.auth = (0, json.dumps({"loggedIn": True, "authMethod": method})
                .encode("utf-8"), b"")
    return cli


@pytest.mark.parametrize("connector, method", [
    ("claude-sub", "api_key"), ("claude-sub", "api_key_helper"),
    ("claude-sub", "oauth_token"), ("claude-sub", "third_party"),
    ("claude-api", "claude.ai"), ("claude-api", "oauth_token"),
    ("claude-api", "api_key_helper"),
])
def test_a_step_whose_cli_logs_in_another_way_is_refused_before_its_call(
        tmp_path, monkeypatch, fake_cli, connector, method):
    cli = a_step_on(tmp_path, monkeypatch, fake_cli, connector, method)
    assert engine.main() != 0
    assert cli.calls == []
    auth = providers.connectors.BUILT_IN[connector]["auth"]
    [line] = lines()
    assert line["auth_method"] == method
    assert line["why"].startswith(connector + " has auth: " + auth + ", and"
                                  " `claude auth status` says it logs in"
                                  " with " + method + ": ")


def test_a_subscription_token_in_the_environment_is_the_subscription(
        tmp_path, monkeypatch, fake_cli):
    cli = a_step_on(tmp_path, monkeypatch, fake_cli, "claude-sub",
                    "oauth_token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "decoy-oauth")
    assert engine.main() == 0
    assert len(cli.calls) == 1


def test_the_api_provider_is_not_asked_how_it_logs_in(tmp_path):
    p = providers.build({"provider": "api", "model": "m", "url": "http://x",
                         "auth": "api-key",
                         "key_file": str(key_file(tmp_path))})
    assert p.read_auth() is None
    assert providers.connectors.method_refused(p) == ""


def test_a_connector_that_inherits_is_never_refused_on_its_auth(
        tmp_path, monkeypatch, fake_cli):
    cli = a_step_on(tmp_path, monkeypatch, fake_cli, "mine", "api_key",
                    more="  mine:\n    provider: cli\n    model: m-small\n")
    assert engine.main() == 0
    [line] = lines()
    assert (line["auth"], line["auth_method"]) == ("inherit", "api_key")
    assert len(cli.calls) == 1


def test_the_cost_lines_carry_connector_and_auth(tmp_path, monkeypatch,
                                                 fake_cli):
    two_connectors(tmp_path, monkeypatch, fake_cli)
    assert engine.main() == 0
    journal = (state.RUNS / "journal.md").read_text(encoding="utf-8")
    [end] = [stops.read(l) for l in journal.split("\n")
             if l.strip() and stops.read(l).kind != "running"]
    assert end.spend.endswith(
        "(claude-api:api-key x1, claude-sub:subscription x1)")
    said = spend.report(state.RUNS)
    at = said.index("per connector")
    assert said[at + 1].startswith("  claude-api (api-key)  1 run, 1 step")
    assert said[at + 2].startswith("  claude-sub (subscription)  1 run, 1 step")
