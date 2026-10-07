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


def risk_map(config, where=None):
    """-> (text, detail). empty text means carry on without it, and the
    detail says why.

    the server runs in `where`, the run's place, so a relative `dir` in the
    arguments means the directory the run works on. the tool's own schema is
    read first: a server is not obliged to refuse a call that leaves out a
    required argument, and one that ranks the files under a `dir` it was not
    given answers with an empty ranking, which looks like no risk at all.
    """
    config = config or {}
    command = config.get("command")
    if not command:
        return "", "no server configured"
    arguments = config.get("arguments") or {}
    if not isinstance(arguments, dict):
        return "", "context: arguments should be a mapping"
    client = Client(command, timeout=int(config.get("timeout", 60)), cwd=where)
    tool = config.get("tool", DEFAULT_TOOL)

    # advisory. a flow does not fail because a side channel is down.
    tools, err = client.list_tools()
    if err:
        return "", err
    if tool not in tools:
        return "", ("the server has no tool " + tool + ". there is: "
                    + ", ".join(tools))
    missing = [a for a in tools[tool].get("required") or [] if a not in arguments]
    if missing:
        return "", (tool + " needs " + ", ".join(missing)
                    + ", and the context block does not give it")

    text, err = client.call_tool(tool, arguments)
    if err:
        return "", err
    if not (text or "").strip():
        return "", tool + " answered with nothing"
    return text, ""


def as_prompt(text):
    if not text.strip():
        return ""
    return (chr(10) + chr(10)
            + "something that has already looked at this code says these are the "
            + "risky places to touch. weight the plan by it:" + chr(10) + chr(10)
            + text.strip() + chr(10))
