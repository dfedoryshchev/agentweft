"""what a flow gets if it says nothing.

a flow with no cap used to mean no cap, which is the wrong default for the
thing that spends money.
"""

def for_flow(spec):
    from runner import settings

    return (settings.get("max_calls", flow=spec),
            settings.get("max_tokens", flow=spec))
