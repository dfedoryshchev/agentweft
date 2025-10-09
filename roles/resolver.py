"""work out what each role actually gets sent, once per run instead of per step."""
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FRAGMENTS = ["role-header", "output-rules", "no-preamble", "no-guessing", "header"]
# some rules only make sense for one role
EXTRA = {"reviewer": ["reviewer-only"]}


def _read(names):
    frag = HERE / "fragments"
    return "".join((frag / (n + ".md")).read_text() for n in names)


def shared_rules():
    return _read(FRAGMENTS)


def resolve(flow, flow_dir):
    """role name -> the rules that role gets. built once, handed to every step."""
    base = shared_rules() + (flow_dir / "instructions.md").read_text()
    out = {}
    for step in flow["steps"]:
        role = step["role"]
        out[role] = base + _read(EXTRA.get(role, []))
    return out
