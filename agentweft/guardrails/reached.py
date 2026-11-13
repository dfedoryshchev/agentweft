"""whether a test run executed given lines of python files: a probe python
loads at its start (a `sitecustomize` in a folder put first on the run's
PYTHONPATH) records each line it sees run, in every process of the run.
the test runs as it would, with no extra run and no pytest special case."""
import ast
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

LOADED = "loaded"
CONFIG = "probe.json"

PROBE = r'''import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


with open(os.path.join(_here, "probe.json"), encoding="utf-8") as _f:
    _targets = [(_norm(p), set(ls)) for p, ls in json.load(_f)]
open(os.path.join(_here, "loaded"), "w").close()
_seen = {}
_hit = set()


def _which(filename):
    try:
        return _seen[filename]
    except KeyError:
        pass
    n = _norm(filename) if filename and filename[0] != "<" else ""
    found = [i for i, (p, _) in enumerate(_targets) if p == n]
    _seen[filename] = found
    return found


def _line(filename, n):
    for i in _which(filename):
        if n in _targets[i][1] and i not in _hit:
            _hit.add(i)
            open(os.path.join(_here, "hit-%d" % i), "w").close()


_mon = getattr(sys, "monitoring", None)
_tool = None
if _mon is not None:
    for _id in (4, 3, 5, 2):
        try:
            _mon.use_tool_id(_id, "agentweft-reached")
        except ValueError:
            continue
        _tool = _id
        break
if _tool is not None:
    def _on_line(code, n):
        _line(code.co_filename, n)
        return _mon.DISABLE

    _mon.register_callback(_tool, _mon.events.LINE, _on_line)
    _mon.set_events(_tool, _mon.events.LINE)
else:
    import threading

    def _local(frame, event, arg):
        if event == "line":
            _line(frame.f_code.co_filename, frame.f_lineno)
        return _local

    def _global(frame, event, arg):
        return _local if _which(frame.f_code.co_filename) else None

    sys.settrace(_global)
    threading.settrace(_global)

# this folder is first on the path, so the project's own sitecustomize, or
# the one of the python it runs on, would never load and the test could
# run differently with the probe than without it
_me = sys.modules.get("sitecustomize")
sys.path[:] = [p for p in sys.path
               if _norm(os.path.abspath(p or ".")) != _norm(_here)]
sys.modules.pop("sitecustomize", None)
try:
    import sitecustomize  # noqa: F401
except ImportError as _e:
    if _e.name != "sitecustomize":
        raise
finally:
    if "sitecustomize" not in sys.modules and _me is not None:
        sys.modules["sitecustomize"] = _me
'''


def lines_of(text, n):
    """-> the lines of python `text` that run as the statement holding line
    `n`: its own lines, not those of the statements nested in it; {n} when
    no statement holds it. raises SyntaxError or ValueError when `text`
    does not parse."""
    best = None
    for node in ast.walk(ast.parse(text)):
        last = getattr(node, "end_lineno", None) or getattr(node, "lineno", 0)
        if isinstance(node, ast.stmt) and node.lineno <= n <= last and (
                best is None or last - node.lineno
                <= best[1] - best[0].lineno):
            best = (node, last)
    if best is None:
        return {n}
    own = set(range(best[0].lineno, best[1] + 1))
    for node in ast.walk(best[0]):
        if isinstance(node, ast.stmt) and node is not best[0]:
            own -= set(range(node.lineno, (node.end_lineno or node.lineno)
                             + 1))
    return own


@contextmanager
def probe(targets):
    """`targets` is [(a python file's path, the lines of it to watch)].
    yields (the folder to put first on the run's PYTHONPATH, a function ->
    None when no process of the run loaded the probe, else the indexes of
    the targets a line of which ran)."""
    with tempfile.TemporaryDirectory(prefix="agentweft-reached-") as tmp:
        folder = Path(tmp)
        (folder / "sitecustomize.py").write_text(PROBE, encoding="utf-8")
        (folder / CONFIG).write_text(json.dumps(
            [[str(p), sorted(ls)] for p, ls in targets]), encoding="utf-8")

        def seen():
            if not (folder / LOADED).exists():
                return None
            return set(i for i in range(len(targets))
                       if (folder / ("hit-" + str(i))).exists())

        yield folder, seen
