"""what a step that writes tests is asked to test, and at which levels.

the levels are settings, read here and handed to the step as values. a brief
that says "integration tests where it makes sense" leaves the model to decide
what makes sense, and the cheapest answer to that is one unit test.

unit tests are always on. integration follows `tests_integration`: true,
false, or auto (the default), which is on when the project has an entry point.
e2e follows `tests_e2e`, off unless a flow turns it on.
"""
from pathlib import Path

from . import settings

FRAGMENT = "tests"
MARK = "{TEST_LEVELS}"
MAIN = ("__main__.py", "main.py")
SCRIPTS = ("[project.scripts]", "[tool.poetry.scripts]")


def entry_point(where):
    """-> where the project's entry point is declared, or "" for none found."""
    root = Path(where)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        for line in pyproject.read_text(encoding="utf-8",
                                        errors="replace").splitlines():
            if line.strip() in SCRIPTS:
                return "pyproject.toml " + line.strip()
    for name in MAIN:
        if (root / name).is_file():
            return name
    if not root.is_dir():
        return ""
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        if (sub / "__main__.py").is_file():
            return sub.name + "/__main__.py"
    return ""


def levels(fm, where):
    """-> [(level, on, why)] for unit, integration and e2e, in that order."""
    out = [("unit", True, "")]
    said = settings.get("tests_integration", flow=fm)
    if said == "auto":
        found = entry_point(where)
        out.append(("integration", bool(found),
                    "the project has an entry point (" + found + ")" if found
                    else "no entry point found"))
    else:
        out.append(("integration", bool(said),
                    "tests_integration is " + str(bool(said)).lower()))
    out.append(("e2e", bool(settings.get("tests_e2e", flow=fm)), ""))
    return out


def as_lines(found):
    lines = []
    for level, on, why in found:
        if on:
            lines.append("    " + level + ": on" + (" - " + why if why else ""))
            continue
        lines.append("    " + level + ": off - " + (why + ", " if why else "")
                     + "do not write " + level + " tests")
    return "\n".join(lines)


def as_prompt(fm, where):
    from agentweft.roles import resolver

    text = resolver.fragment(FRAGMENT)
    return "\n\n" + text.replace(MARK, as_lines(levels(fm, where))).rstrip("\n") \
        + "\n"
