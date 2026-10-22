import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.runner import errors


def test_classify_timeout_is_transient():
    assert runner.classify("Error: request timed out after 300s") is errors.Transient


def test_classify_missing_key_is_fatal():
    assert runner.classify("invalid api key") is errors.Fatal


SAFEGUARDS = ("API Error: Claude Sonnet 5.5's safeguards flagged this message."
              " Please rephrase your request.")


def test_a_message_the_providers_safeguards_flagged_is_not_asked_again():
    assert runner.classify(SAFEGUARDS) is errors.Fatal


def test_a_cli_answer_the_safeguards_refused_is_one_charged_go():
    import types

    from agentweft.providers import cli_provider

    p = cli_provider.CliProvider(command="claude")
    said = p.read({"type": "result", "is_error": True, "result": SAFEGUARDS,
                   "total_cost_usd": 0.11,
                   "usage": {"input_tokens": 9000, "output_tokens": 0}},
                  types.SimpleNamespace(returncode=1, killed=False))
    assert errors.kind_of(said) is errors.Fatal
    assert said.cost == 0.11


def test_unknown_stderr_is_transient():
    # going again is cheap, giving up is not
    assert runner.classify("something nobody has seen before") is errors.Transient


def test_retry_stops_at_the_cap():
    tries = []

    def never():
        tries.append(1)
        return False, ""

    assert runner.retry(never, cap=3, sleep=lambda s: None) == ""
    assert len(tries) == 3


def test_retry_gives_each_call_its_own_budget():
    # this is the one that bit me in august
    for _ in range(2):
        tries = []

        def never():
            tries.append(1)
            return False, ""

        runner.retry(never, cap=2, sleep=lambda s: None)
        assert len(tries) == 2
