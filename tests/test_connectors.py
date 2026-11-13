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
    assert p.refuses() == ("claude-api has auth: api-key and no key_file:"
                           " declare one under connectors:")


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
    path = key_file(tmp_path, "decoy-first")
    p = providers.build("claude-api", connectors={
        "claude-api": {"key_file": str(path)}})
    assert p.refuses() == ""
    path.write_text("decoy-second", encoding="utf-8")
    assert p.ask("go", timeout=5)
    assert cli.calls[0]["kw"]["env"]["ANTHROPIC_API_KEY"] == "decoy-second"


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
    first, second = key_file(tmp_path, name="a.txt"), key_file(tmp_path,
                                                              name="b.txt")
    held = project.Held(tmp_path / "project.yml",
                        "project:\n  name: here\nconnectors:\n  claude-api:\n"
                        "    key_file: " + json.dumps(str(first)) + "\n"
                        "  cheap:\n    provider: cli\n    model: m-cheap\n")
    got = providers.connectors.declared({"connectors": {
        "claude-api": {"key_file": str(second)}}}, held)
    assert got["claude-api"]["key_file"] == str(second)
    assert got["cheap"] == {"provider": "cli", "model": "m-cheap"}


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
    a_flow(tmp_path, monkeypatch, [("worker", ["provider: claude-api"])],
           project_yml="project:\n  name: here\n"
           + declared_key(key_file(tmp_path)))
    cli = fake_cli(answer("done\n"))
    assert engine.main() == 0
    assert cli.calls[0]["kw"]["env"]["ANTHROPIC_API_KEY"] == KEY


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
    cli.auth = (0, b'{"loggedIn": true, "authMethod": "apiKey",'
                   b' "email": "someone@example.com"}\n', b"")
    return place, cli


def test_every_step_line_says_its_connector_and_auth(tmp_path, monkeypatch,
                                                     fake_cli):
    two_connectors(tmp_path, monkeypatch, fake_cli)
    assert engine.main() == 0
    api, sub = lines()
    assert (api["connector"], api["auth"], api["auth_method"]) == (
        "claude-api", "api-key", "apiKey")
    assert (sub["connector"], sub["auth"]) == ("claude-sub", "subscription")
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
    assert lines()[2]["auth_method"] == "apiKey"


def test_an_unreadable_auth_status_leaves_the_method_out(
        tmp_path, monkeypatch, fake_cli):
    place, cli = two_connectors(tmp_path, monkeypatch, fake_cli)
    cli.auth = (0, b"not json\n", b"")
    assert engine.main() == 0
    api, sub = lines()
    assert "auth_method" not in api and api["auth"] == "api-key"


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
