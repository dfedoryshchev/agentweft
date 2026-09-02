"""work out what each role actually gets sent, once per run instead of per step."""
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
# what a role is, in whatever flow it turns up in: a reviewer answers with a
# verdict, a merge invents nothing. it was copied into every flow that used
# the role, so five reviewers carried the same block and the sixth quietly
# did not.
LIBRARY = Path(__file__).resolve().parent / "library"
# output-rules and no-guessing live under skills/ now. the other three have
# not earned the frontmatter yet.
FRAGMENTS = ["role-header", "no-preamble", "header"]
# some rules only make sense for one role
EXTRA = {"reviewer": ["reviewer-only"], "verify": ["reviewer-only"],
         "worker": ["multi-file"], "patcher": ["multi-file"]}


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


def library_roles():
    """the roles the library keeps words for. the rest are the flow's own."""
    if not LIBRARY.exists():
        return []
    return sorted(p.stem for p in LIBRARY.glob("*.md"))


def role_prompt(name):
    """what the library says about a role, or "" when it says nothing.

    `name` is the prompt's file name, which is the role's name in every flow
    that does not point a step at some other file. a role the library has
    never heard of is not an error - most of what a worker is told is about
    the flow it is in, and there is nothing to hoist.
    """
    path = LIBRARY / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def resolve(flow, flow_dir, promises=""):
    """role name -> the rules that role gets. built once, handed to every step."""
    base = shared_rules() + skill_rules() + (flow_dir / "instructions.md").read_text() + promises
    out = {}
    for step in flow["steps"]:
        role = step["role"]
        out[role] = base + _read(EXTRA.get(role, []))
    return out
