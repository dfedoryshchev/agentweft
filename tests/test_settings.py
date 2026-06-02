import sys

sys.path.insert(0, ".")
from agentweft.runner import settings


def test_the_step_beats_the_flow():
    assert settings.get("workers", step={"workers": 9}, flow={"workers": 2}) == 9


def test_the_flow_beats_the_default():
    assert settings.get("timeout", flow={"timeout": 999}) == 999


def test_the_default_is_the_floor():
    assert settings.get("timeout") == settings.DEFAULTS["timeout"]


def test_an_explicit_zero_is_not_treated_as_absent():
    # `or` would have swallowed this and quietly used the default
    assert settings.get("max_calls", flow={"max_calls": 0}) == 0


def test_an_unknown_key_is_none_rather_than_a_guess():
    assert settings.get("nonsense") is None
