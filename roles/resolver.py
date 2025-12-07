"""work out what each role actually gets sent, once per run instead of per step."""
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
# output-rules and no-guessing live under skills/ now. the other three have
# not earned the frontmatter yet.
FRAGMENTS = ["role-header", "no-preamble", "header"]
# some rules only make sense for one role
EXTRA = {"reviewer": ["reviewer-only"], "verify": ["reviewer-only"]}


def _read(names):
    frag = HERE / "fragments"
    return "".join((frag / (n + ".md")).read_text() for n in names)


def skill_rules():
    # the skill files have frontmatter and the fragments do not, so this is
    # _read again with three extra lines. wrong, sort it later.
    out = ""
    skills = HERE / "skills"
    if not skills.exists():
        return out
    for skill in sorted(skills.iterdir()):
        text = (skill / "SKILL.md").read_text()
        if text.startswith("---"):
            text = text.split("---", 2)[2]
        out = out + text
    return out


def shared_rules():
    return _read(FRAGMENTS)


def resolve(flow, flow_dir):
    """role name -> the rules that role gets. built once, handed to every step."""
    base = shared_rules() + skill_rules() + (flow_dir / "instructions.md").read_text()
    out = {}
    for step in flow["steps"]:
        role = step["role"]
        out[role] = base + _read(EXTRA.get(role, []))
    return out
