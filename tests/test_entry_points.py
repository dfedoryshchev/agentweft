import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def fresh(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, *args], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("module", ["agentweft.evals", "agentweft.bench"])
def test_a_documented_command_starts_in_a_fresh_process(module):
    r = fresh("-m", module)
    assert "ImportError" not in r.stderr, r.stderr
    assert "usage: python -m " + module in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("module", [
    "agentweft.guardrails.gates",
    "agentweft.guardrails.redorder",
    "agentweft.mcp.preflight",
    "agentweft.bench.mutants",
])
def test_a_module_imports_first_in_a_fresh_process(module):
    r = fresh("-c", "import " + module)
    assert r.returncode == 0, r.stderr


def test_the_mcp_package_still_hands_out_its_server_and_client():
    r = fresh("-c", "from agentweft.mcp import Client, serve; "
              "print(Client.__name__, serve.__name__)")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["Client", "serve"]
