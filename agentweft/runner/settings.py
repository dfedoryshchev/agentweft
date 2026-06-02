"""where a setting comes from, decided once.

there were three ways to configure something: the flow file, the environment,
and a default sitting in whichever module happened to need it. they disagreed,
and which one won depended on where you looked.

order, highest first: the step, the flow, the environment, the default.
"""

DEFAULTS = {"timeout": 300, "retries": 3, "workers": 3,
            "max_calls": 25, "max_tokens": 200000}


def get(key, step=None, flow=None, env=None, default=None):
    for source in (step, flow):
        if source and source.get(key) is not None:
            return source[key]
    if env is not None:
        return env
    if default is not None:
        return default
    return DEFAULTS.get(key)
