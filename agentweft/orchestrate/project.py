"""what agentweft needs to know about ONE codebase, in one file beside it.

the roles, the phases, the gates and the tool grants ship with agentweft and
are meant to be true of any codebase. they are not, quite. every role still
carries a MANDATORY PRE-WORK list, seven of them name a file path, and between
them they name three paths that were true of the codebase the prompts were
written in. two of the three do not exist in this repo. the third does, and it
is about this repo's own layers rather than the layers the role was written to
rule on, which is the worse of the two failures: a missing path stops in front
of you, a path that resolves to the wrong document is read and reported as done.

so the sentence is split. the role says what it needs to have READ - the
layering rules, the test layout, how features are normally built here - and
this file says where that lives in one codebase. the role library already works
that way: four role files under `roles/library/`, not one of them naming a path.

the file carries its own thesis in its section names, and it is the whole
reason `standards` and `gates` are not one key:

    standards:  PROSE. it reaches a prompt. it can be read, agreed with, and
                then not done, and nothing will know.
    coverage:   NUMBERS. one somebody picked while looking at one codebase,
                which is why the number is here and not in the role.
    gates:      PROGRAMS. argv, an exit code, no opinion involved.

nothing reads any of this yet, and saying so is half the point of the row it
arrives in. what it has is a format and a loader that refuses a word it has no
name for, on the pattern flow.yaml has used for months - a typo in a file like
this would otherwise sit there looking exactly like a rule.

the two closed vocabularies it does not own are borrowed rather than restated.
a tier is `spec.TIERS` and a grant is `spec.GRANTS`, because a second list of
what `high` means is how one repo ends up with two answers.
"""
import re

from agentweft.flow import reader, spec

from . import workflow

REQUIRED = ("project",)
KNOWN = ("project", "read_first", "standards", "coverage", "gates", "roles")
PROJECT_KNOWN = ("name", "stack")
STANDARDS_KNOWN = ("forbidden", "immediate_reject")
COVERAGE_KNOWN = ("critical", "overall")
ROLE_KNOWN = ("model", "tools")

# a path as it appears in a prompt: something in backticks with a separator in
# it. crude, and it only has to find the thing the file exists to take away.
PATH = re.compile(r"`([^`\s]+/[^`\s]+)`")


def in_prose(text):
    """-> the paths a prompt names, sorted, deduplicated."""
    return sorted(set(PATH.findall(text)))


def path():
    return workflow.root() / "project.yml"


def example():
    return workflow.root() / "project.example.yml"


class Project(object):
    """one codebase's answers. every accessor gives back nothing rather than

    raising, because a project file is allowed to be silent about a role, a
    gate or a number - silence means the shipped default, not an error.
    """

    __slots__ = ("raw", "name", "stack")

    def __init__(self, raw):
        self.raw = raw
        said = raw.get("project") or {}
        self.name = said.get("name", "")
        self.stack = list(said.get("stack") or [])

    def _block(self, key, name):
        return (self.raw.get(key) or {}).get(name)

    def read_first(self, role):
        return list(self._block("read_first", role) or [])

    def standards(self, kind):
        return list(self._block("standards", kind) or [])

    def coverage(self, kind):
        return self._block("coverage", kind)

    def gate(self, name):
        return list(self._block("gates", name) or [])

    def role(self, name):
        return dict(self._block("roles", name) or {})


def _strings(bad, where, value):
    if not isinstance(value, list):
        bad.append(where + " should be a list")
        return
    for item in value:
        if not isinstance(item, str):
            bad.append(where + ": " + str(item) + " should be str")


def _mapping(bad, where, value):
    if isinstance(value, dict):
        return True
    bad.append(where + " should be a mapping")
    return False


def _unknown(bad, where, block, allowed):
    for key in block:
        if key not in allowed:
            bad.append(where + "unknown key " + str(key))


def _check_project(bad, block):
    if not _mapping(bad, "project", block):
        return
    _unknown(bad, "project: ", block, PROJECT_KNOWN)
    if "name" not in block:
        bad.append("project: missing name")
    elif not isinstance(block["name"], str):
        bad.append("project: name should be str")
    if block.get("stack") is not None:
        _strings(bad, "project: stack", block["stack"])


def _check_read_first(bad, block):
    if not _mapping(bad, "read_first", block):
        return
    for role, paths in block.items():
        _strings(bad, "read_first: " + str(role), paths)


def _check_standards(bad, block):
    if not _mapping(bad, "standards", block):
        return
    _unknown(bad, "standards: ", block, STANDARDS_KNOWN)
    for key in STANDARDS_KNOWN:
        if block.get(key) is not None:
            _strings(bad, "standards: " + key, block[key])


def _check_coverage(bad, block):
    if not _mapping(bad, "coverage", block):
        return
    _unknown(bad, "coverage: ", block, COVERAGE_KNOWN)
    for key in COVERAGE_KNOWN:
        got = block.get(key)
        if got is None:
            continue
        # `critical: yes` loads as True, and True IS an int in python, so
        # without this it passes the type check and then passes the range
        # check as 1 - a coverage floor of one percent that nobody typed.
        if isinstance(got, bool) or not isinstance(got, int):
            bad.append("coverage: " + key + " should be int")
        elif not 0 <= got <= 100:
            bad.append("coverage: " + key + " should be 0 to 100")


def _check_gates(bad, block):
    if not _mapping(bad, "gates", block):
        return
    for name, argv in block.items():
        where = "gates: " + str(name)
        if not isinstance(argv, list):
            bad.append(where + " should be a list")
            continue
        if not argv:
            bad.append(where + " is empty")
        _strings(bad, where, argv)


def _check_roles(bad, block):
    if not _mapping(bad, "roles", block):
        return
    for role, said in block.items():
        where = "roles: " + str(role)
        if not _mapping(bad, where, said):
            continue
        _unknown(bad, where + ": ", said, ROLE_KNOWN)
        if said.get("model") and said["model"] not in spec.TIERS:
            bad.append(where + ": model should be one of " + ", ".join(spec.TIERS))
        # `is not None` rather than truthiness: `tools: []` is a role saying it
        # may touch nothing, which is a grant and not a missing one.
        if said.get("tools") is not None:
            if not isinstance(said["tools"], list):
                bad.append(where + ": tools should be a list")
            else:
                for tool in said["tools"]:
                    if tool not in spec.GRANTS:
                        bad.append(where + ": no such tool " + str(tool)
                                   + ". there is: " + ", ".join(spec.GRANTS))


CHECKS = (("project", _check_project), ("read_first", _check_read_first),
          ("standards", _check_standards), ("coverage", _check_coverage),
          ("gates", _check_gates), ("roles", _check_roles))


def check(raw):
    """-> list of complaints, in flow.yaml's words and in the file's order."""
    if not isinstance(raw, dict):
        return ["should be a mapping"]
    bad = []
    for key in REQUIRED:
        # `is None` rather than `not in`: a bare `project:` with nothing under
        # it is in the file and answers for nothing, which is the same hole as
        # leaving it out and would otherwise pass.
        if raw.get(key) is None:
            bad.append("missing " + key)
    _unknown(bad, "", raw, KNOWN)
    for key, checker in CHECKS:
        if raw.get(key) is not None:
            checker(bad, raw[key])
    return bad


def load(raw):
    bad = check(raw)
    if bad:
        raise ValueError("project.yml: " + "; ".join(bad))
    return Project(raw)


def read(p=None):
    """the file the way a flow file is read: one reader, duplicate keys refused.

    two `gates:` blocks under safe_load would keep the last, which is a file
    running half of what it says it runs - and the gates are the half that is
    supposed to be impossible to ignore.
    """
    p = p or path()
    return load(reader.read(p.read_text(encoding="utf-8")) or {})


def pre_work(agent, proj=None):
    """what one seat is actually handed to read first.

    -> `proj`'s own answer when it has one, in the order it gives it. the
    seat's own prose otherwise, found the way `hardcoded()` finds it: a
    project silent about a role is not a project with nothing to read, it is
    one nobody has answered for yet.
    """
    said = proj.read_first(agent.name) if proj is not None else []
    if said:
        return said
    if not agent.prompt().exists():
        return []
    return in_prose(agent.prompt().read_text(encoding="utf-8"))


def hardcoded(wf=None):
    """seats whose own prompt names a path. -> the seats, in workflow order.

    countable rather than raised, the same as `ungranted()` and `misnamed()`:
    it is a gap in the prompt files, not a failure of a loader. this is the
    number the file exists to bring down, and nothing brings it down yet.
    """
    wf = wf or workflow.load()
    out = []
    for phase in wf.phases:
        for agent in phase.agents:
            prompt = agent.prompt()
            if prompt.exists() and in_prose(prompt.read_text(encoding="utf-8")):
                out.append(agent)
    return out
