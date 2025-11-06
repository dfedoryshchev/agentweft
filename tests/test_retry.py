import sys

sys.path.insert(0, ".")
import runner
from runner import errors


def test_classify_timeout_is_transient():
    assert runner.classify("Error: request timed out after 300s") is errors.Transient


def test_classify_missing_key_is_fatal():
    assert runner.classify("invalid api key") is errors.Fatal


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
