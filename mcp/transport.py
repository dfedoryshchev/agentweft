"""line delimited json over two streams. knows nothing about flows."""
import json
import sys


def read(stream):
    line = stream.readline()
    if not line:
        return None
    return json.loads(line)


def write(stream, payload):
    stream.write(json.dumps(payload) + "\n")
    stream.flush()


def loop(handle, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    while True:
        msg = read(stdin)
        if msg is None:
            return 0
        try:
            result = handle(msg)
            if msg.get("id") is None:
                continue
            write(stdout, {"jsonrpc": "2.0", "id": msg.get("id"), "result": result})
        except Exception as e:
            write(stdout, {"jsonrpc": "2.0", "id": msg.get("id"),
                           "error": {"code": -32603, "message": str(e)}})
