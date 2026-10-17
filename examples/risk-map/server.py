"""a stand-in for `warpmap mcp`, so the example runs with nothing installed.

same wire and same answer shape: one json-rpc message per line on stdin, one
reply per line on stdout, a `hotspots` tool that needs `dir`, and a ranking of
`path  score` lines, riskiest first. it does not look at the code under `dir`:
the ranking is the sample project warpmap's own readme ranks.
"""
import json
import os
import sys

RANKING = """\
src/store/session.ts  1.000
src/api/client.ts  0.360
src/ui/Widget.tsx  0.096
src/util/format.ts  0.072
src/util/uuid.ts  0.024
src/api/index.ts  0.008
src/store/index.ts  0.008
"""

HOTSPOTS = {"name": "hotspots",
            "description": "rank the riskiest files (churn x complexity)",
            "inputSchema": {"type": "object",
                            "properties": {"dir": {"type": "string"}},
                            "required": ["dir"]}}


def text(said, failed=False):
    out = {"content": [{"type": "text", "text": said}]}
    if failed:
        out["isError"] = True
    return out


def call(params):
    name = params.get("name")
    if name != "hotspots":
        return text("unknown tool: " + str(name))
    where = (params.get("arguments") or {}).get("dir")
    if not where or not os.path.isdir(where):
        return text("dir: not a directory: " + str(where), failed=True)
    return text(RANKING)


def answer(msg):
    method = msg.get("method")
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        return {"protocolVersion": asked, "capabilities": {"tools": {}},
                "serverInfo": {"name": "risk-map-example", "version": "0"}}
    if method == "tools/list":
        return {"tools": [HOTSPOTS]}
    if method == "tools/call":
        return call(msg.get("params") or {})
    return None


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        result = answer(msg) if isinstance(msg, dict) else None
        # warpmap skips what it does not answer, notifications included
        if result is None or msg.get("id") is None:
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                     "result": result}) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
