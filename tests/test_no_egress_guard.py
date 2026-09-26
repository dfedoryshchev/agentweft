import sys

import pytest

sys.path.insert(0, ".")
from agentweft import providers


def test_the_api_provider_is_refused_under_the_guard(monkeypatch):
    monkeypatch.setenv("API_KEY", "x")
    p = providers.build({"provider": "api"})
    # DID NOT RAISE here would mean ask() stopped going through httpx.post -
    # the only seam the guard patches - and got past this test to a real
    # request instead of the guard's refusal.
    with pytest.raises(pytest.fail.Exception):
        p.ask("hello", timeout=1)


def test_the_cli_provider_is_refused_under_the_guard():
    p = providers.build({"provider": "cli"})
    with pytest.raises(pytest.fail.Exception):
        p.ask("hello", timeout=1)


def test_the_default_provider_is_refused_under_the_guard():
    p = providers.build({})
    with pytest.raises(pytest.fail.Exception):
        p.ask("hello", timeout=1)
