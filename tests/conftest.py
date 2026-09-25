import subprocess
import sys
import types

import httpx
import pytest

sys.path.insert(0, ".")
from agentweft.providers import cli_provider


def refuse(what):
    def refused(*args, **kw):
        pytest.fail(what + " was called from a test. a test talks to the fake "
                    "provider, or patches this itself.")
    return refused


@pytest.fixture(autouse=True, scope="session")
def no_real_provider():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "post", refuse("httpx.post"))
        # the provider's own name for the module, not subprocess.run itself:
        # the mcp client, the mcp server and the command gate spawn processes
        # on purpose and share that module.
        mp.setattr(cli_provider, "subprocess", types.SimpleNamespace(
            run=refuse("the cli provider's subprocess.run"),
            TimeoutExpired=subprocess.TimeoutExpired))
        yield
