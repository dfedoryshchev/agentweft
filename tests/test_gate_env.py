"""a gate runs the project's commands and the tests a model wrote, so none of
them is started with the provider credentials the run holds."""
import subprocess
import sys
import types

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import gates, signoff, starttests
from agentweft.guardrails.gates import base, redfirst_gate, redtest_gate

DECOYS = {"ANTHROPIC_API_KEY": "decoy-key", "ANTHROPIC_AUTH_TOKEN":
           "decoy-token", "CLAUDE_CODE_OAUTH_TOKEN": "decoy-oauth",
           "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "decoy-refresh",
           "API_KEY": "decoy-api", "anthropic_base_url": "decoy-url"}
# exits 3 when any decoy name reached it, 4 when an ordinary one did not
CHECK = ("import os, sys; names = {k.upper() for k in os.environ}; "
         "sys.exit(3 if names & set(" + repr(sorted(n.upper() for n in DECOYS))
         + ") else 0 if os.environ.get('PLAIN_VALUE') == 'kept' else 4)")


@pytest.fixture(autouse=True)
def decoys(monkeypatch):
    for name, value in DECOYS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PLAIN_VALUE", "kept")


def spy(monkeypatch, module):
    """-> the exit codes of the children `module` starts, each run for real
    with the environment it was handed."""
    seen = []

    def run(argv, **kw):
        r = subprocess.run(argv, **kw)
        seen.append((kw.get("env"), r.returncode))
        return r

    monkeypatch.setattr(module, "subprocess", types.SimpleNamespace(
        run=run, TimeoutExpired=subprocess.TimeoutExpired))
    return seen


def held(env):
    names = {k.upper() for k in (env or {})}
    return env is not None and not names & {n.upper() for n in DECOYS} \
        and env.get("PLAIN_VALUE") == "kept"


def test_the_python_a_gate_starts_holds_no_credential():
    with base.fresh_python() as env:
        assert held(env)
    with base.fresh_python(dict(DECOYS, PLAIN_VALUE="kept")) as env:
        assert held(env)


def test_a_command_gate_s_child_sees_no_credential(tmp_path):
    r = gates.build({"gate": "command",
                     "command": [sys.executable, "-c", CHECK]},
                    where=tmp_path).run("anything")
    assert r.ok, r.detail


def test_a_red_test_gate_s_child_sees_no_credential(tmp_path, monkeypatch):
    seen = spy(monkeypatch, redtest_gate)
    redtest_gate.RedTestGate().judged([sys.executable, "-c", CHECK],
                                      tmp_path, False, "", {"EXTRA": "1"})
    assert seen and all(code == 0 and held(env) for env, code in seen)


def test_a_red_first_gate_s_child_sees_no_credential(tmp_path, monkeypatch):
    seen = spy(monkeypatch, redfirst_gate)
    redfirst_gate.RedFirstGate().ran([sys.executable, "-c", CHECK], "t",
                                     tmp_path, None, 60)
    assert seen and all(code == 0 and held(env) for env, code in seen)


def test_the_start_tests_run_sees_no_credential(tmp_path, monkeypatch):
    seen = spy(monkeypatch, starttests)
    starttests.run_tests([sys.executable, "-c", CHECK], [], tmp_path, 60)
    assert seen and all(code == 0 and held(env) for env, code in seen)


def test_the_hidden_suite_and_an_mcp_server_see_no_credential(tmp_path,
                                                             monkeypatch):
    from agentweft.bench import scorer
    from agentweft.mcp import client

    handed = []
    monkeypatch.setattr(scorer, "bounded",
                        lambda argv, where, env, limit: handed.append(env))
    scorer.pytest(tmp_path, ["t.py"], env={"TASK_REPO": "r"})
    seen = spy(monkeypatch, client)
    client.Client([sys.executable, "-c", CHECK])._session([])
    assert held(handed[0]) and handed[0]["TASK_REPO"] == "r"
    assert seen and all(code == 0 and held(env) for env, code in seen)


def test_the_sign_off_s_git_sees_no_credential(tmp_path, monkeypatch):
    seen = spy(monkeypatch, signoff)
    signoff._git(tmp_path, "--version")
    signoff.merged(tmp_path, [], "HEAD")
    assert seen and all(held(env) for env, _ in seen)
