"""what a flow gets if it says nothing.

a flow with no cap used to mean no cap, which is the wrong default for the
thing that spends money.
"""

MAX_CALLS = 25
MAX_TOKENS = 200000


def for_flow(spec):
    return (spec.get("max_calls") or MAX_CALLS,
            spec.get("max_tokens") or MAX_TOKENS)
