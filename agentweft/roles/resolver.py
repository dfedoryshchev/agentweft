"""work out what each role actually gets sent, once per run instead of per step."""
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
# what a role is, in whatever flow it turns up in: a reviewer answers with a
# verdict, a merge invents nothing. it was copied into every flow that used
# the role, so five reviewers carried the same block and the sixth quietly
# did not.
LIBRARY = Path(__file__).resolve().parent / "library"
# output-rules and no-guessing live under skills/ now. the other four have
# not earned the frontmatter yet. handoff goes last: it is the end of every
# answer, and it is what the next step reads first.
FRAGMENTS = ["role-header", "no-preamble", "header", "handoff"]
# some rules only make sense for one role
EXTRA = {"reviewer": ["reviewer-only"], "verify": ["reviewer-only"],
         "judge": ["reviewer-only"], "worker": ["multi-file"],
         "patcher": ["multi-file"]}


def _read(names):
    frag = HERE / "fragments"
    return "".join((frag / (n + ".md")).read_text(encoding="utf-8")
                   for n in names)


def fragment(name):
    return _read([name])


def _skill(path):
    """-> (the role its frontmatter names or "", its body)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return "", text
    _, head, body = text.split("---", 2)
    role = ""
    for line in head.split("\n"):
        key, _, value = line.partition(":")
        if key.strip() == "role":
            role = value.strip()
    return role, body


def skill(name):
    """-> one skill's body, without its frontmatter."""
    return _skill(HERE / "skills" / name / "SKILL.md")[1]


def skill_rules(role=None):
    """every skill's body, in name order. a skill whose frontmatter names a
    role is that role's procedure and goes to no other."""
    out = ""
    skills = HERE / "skills"
    if not skills.exists():
        return out
    for path in sorted(skills.iterdir()):
        own, body = _skill(path / "SKILL.md")
        if not own or own == role:
            out = out + body
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

    `name` is a file in the library, so it is the ROLE's name and not the
    step's prompt file; the caller is the one that knows which role a step
    declared. a role the library has never heard of is not an error - most of
    what a worker is told is about the flow it is in, and there is nothing to
    hoist.
    """
    path = LIBRARY / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def resolve(flow, flow_dir, promises=""):
    """role name -> the rules that role gets. built once, handed to every step."""
    own = flow_dir / "instructions.md"
    words = own.read_text(encoding="utf-8") if own.is_file() else ""
    shared = shared_rules()
    out = {}
    for step in flow["steps"]:
        role = step["role"]
        out[role] = shared + skill_rules(role) + words + promises \
            + _read(EXTRA.get(role, []))
    return out
