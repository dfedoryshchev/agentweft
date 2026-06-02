import sys

import pytest

sys.path.insert(0, ".")
from agentweft import providers


def test_the_default_is_the_cli():
    p = providers.build({})
    assert p.name == "cli"


def test_an_unknown_provider_names_the_ones_there_are():
    with pytest.raises(ValueError) as e:
        providers.build({"provider": "telepathy"})
    assert "cli" in str(e.value)


def test_options_reach_the_provider():
    p = providers.build({"provider": "cli", "command": "somethingelse"})
    assert p.opts["command"] == "somethingelse"


def test_check_reports_a_missing_binary_rather_than_raising():
    p = providers.build({"provider": "cli", "command": "definitely-not-real"})
    ok, detail = p.check()
    assert not ok
    assert "PATH" in detail


def test_the_api_provider_never_hardcodes_a_model(monkeypatch):
    monkeypatch.delenv("MODEL", raising=False)
    p = providers.build({"provider": "api"})
    assert p._model() == ""
