"""what a tool server can tell a flow before it starts.

a flow that is about to work on a codebase can ask something that already knows
the shape of it. right now that is a ranking of which files are risky to touch,
which goes into the planner's prompt so the plan is ordered by blast radius
instead of by whatever it read first.

the server is named in the flow file - `command` is whatever binary speaks the
protocol. nothing in here knows or cares which tool it is, and the shipped
config is a placeholder rather than the one i happen to run.
"""
from .client import Client

DEFAULT_TOOL = "hotspots"


def risk_map(config):
    """-> (text, detail). empty text means carry on without it."""
    command = (config or {}).get("command")
    if not command:
        return "", "no server configured"
    client = Client(command, timeout=int((config or {}).get("timeout", 60)))
    tool = (config or {}).get("tool", DEFAULT_TOOL)
    text, err = client.call_tool(tool, (config or {}).get("arguments"))
    if err:
        # advisory. a flow does not fail because a side channel is down.
        return "", err
    return text or "", ""


def as_prompt(text):
    if not text.strip():
        return ""
    return (chr(10) + chr(10)
            + "something that has already looked at this code says these are the "
            + "risky places to touch. weight the plan by it:" + chr(10) + chr(10)
            + text.strip() + chr(10))
