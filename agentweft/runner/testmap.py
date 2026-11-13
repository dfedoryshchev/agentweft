"""the tests already near a change, handed to the steps that write tests.

a step that writes tests without reading the suite already there adds new
tests beside the ones that check the same case, and the copies pile up. so
before such a step the runner lists, at no model cost, every test whose file
mirrors a product file the request or the plan names (`test_<name>`,
`<name>_test`, `<name>.test`), or imports it, nearest first, grouped by tier
from its folder or file name (`integration`, `e2e`; every other test is a
unit test), and capped: what does not fit is named by its file.

python tests are listed by id as pytest takes them (`file::name`), a
javascript test by its `test(` or `it(` title, any other test file by name.
"""
import ast
import os
import re
from pathlib import Path, PurePosixPath

from agentweft.guardrails.snapshot import is_test, test_ids

HEAD = ("the tests already near this change, by tier, nearest first. a case"
        " one of them already checks is an update of that test (a new"
        " parametrize case, or a new test function in its file), named with"
        " its id on a DID line; a new test only for a case none of them"
        " covers.")
MOST = 40
CAP = 1500
TIERS = ("unit", "integration", "e2e")
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
        "build", "facts"}
TITLED = re.compile(r"""\b(?:it|test)\s*\(\s*(['"`])(.+?)\1""")
NAMED = re.compile(r"[\w./\\-]+\.[A-Za-z]{1,5}\b")
CODE = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".cs")


def tier_of(rel):
    """-> the tier a test file is in, read from its folders and its name."""
    words = re.split(r"[/_.\-]", rel.lower())
    if "e2e" in words:
        return "e2e"
    if "integration" in words:
        return "integration"
    return "unit"


def named(where, texts):
    """-> the product files of the place `texts` name, in the order named:
    a code file there, not a test."""
    root = Path(where)
    out = []
    for text in texts:
        for m in NAMED.finditer(text or ""):
            rel = re.sub(r"^(\.\.?/)+", "", m.group(0).replace("\\", "/"))
            rel = rel.rstrip(".")
            if rel.endswith(CODE) and not is_test(rel) and rel not in out \
                    and (root / rel).is_file():
                out.append(rel)
    return out


def files_of(where):
    """-> every test file of the place, by path from it, in path order."""
    root = Path(where)
    out = []
    for top, dirs, files in os.walk(str(root)):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in files:
            rel = Path(top, name).relative_to(root).as_posix()
            if is_test(rel) and rel.endswith(CODE):
                out.append(rel)
    return sorted(out)


def mirrors(rel, stems):
    name = PurePosixPath(rel).name.lower()
    words = re.split(r"[_.\-]", name)
    return any(s.lower() in words for s in stems)


def imports(text, rel, modules, stems):
    """whether test source `text` imports one of the product files: by its
    dotted module or its name in python, by a path ending in its name in
    javascript."""
    if rel.endswith(".py"):
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                names = [base] + [(base + "." if base else "") + a.name
                                  for a in node.names]
            else:
                continue
            if any(n in modules or n.split(".")[-1] in stems for n in names):
                return True
        return False
    return any(re.search(r"""(['"`])[^'"`]*\b""" + re.escape(s)
                         + r"""(\.[cm]?[jt]sx?)?\1""", text) for s in stems)


def ids_of(text, rel):
    if rel.endswith(".py"):
        found = test_ids(text, rel)
        return list(found) if found else [rel]
    titles = [m.group(2) for m in TITLED.finditer(text)]
    return [rel + "::" + t for t in titles] or [rel]


def near(where, texts):
    """-> [(tier, file, its test ids)] for the test files near the product
    files `texts` name, the ones that mirror one first, then the ones that
    import one, each in path order."""
    if where is None:
        return []
    found = named(where, texts)
    if not found:
        return []
    stems = sorted({PurePosixPath(p).stem for p in found})
    modules = {p.rsplit(".", 1)[0].replace("/", ".") for p in found}
    first, then = [], []
    for rel in files_of(where):
        try:
            text = (Path(where) / rel).read_text(encoding="utf-8",
                                                 errors="replace")
        except OSError:
            continue
        if mirrors(rel, stems):
            first.append((tier_of(rel), rel, ids_of(text, rel)))
        elif imports(text, rel, modules, stems):
            then.append((tier_of(rel), rel, ids_of(text, rel)))
    return first + then


def lines(found):
    """-> the lines handed to the step, under MOST ids and CAP characters;
    [] for none. what does not fit is named by its file."""
    if not found:
        return []
    out, size, shown, left = [HEAD], len(HEAD), 0, []
    for tier in TIERS:
        group = [f for f in found if f[0] == tier]
        if not group:
            continue
        said = []
        for _, rel, ids in group:
            more = 0
            for i in ids:
                line = "- " + i
                extra = len(line) + 1 + (0 if said else len(tier) + 2)
                if shown >= MOST or size + extra > CAP:
                    more += 1
                    continue
                said.append(line)
                shown += 1
                size += extra
            if more:
                left.append(rel + " (" + str(more) + ")")
        if said:
            out.append(tier + ":")
            out.extend(said)
    if left:
        out.append("more tests left out at the cap, open them yourself: "
                   + ", ".join(left))
    return out


def as_prompt(where, texts):
    """-> the end of a test-writing step's prompt, "" when no test is near."""
    found = lines(near(where, texts))
    return "\n\n" + "\n".join(found) + "\n" if found else ""


def supplied(ids):
    """-> what a step that writes tests is told when the red test it was
    handed is one the run started with, unchanged, that a red-test gate saw
    fail: that test is the proof, and only a boundary or an error path it
    does not name earns a case. "" for no such test."""
    if not ids:
        return ""
    one = len(ids) == 1
    return ("\n\n" + ("the test" if one else "the tests") + " you were given ("
            + ", ".join(ids) + ") " + ("was" if one else "were") + " in the"
            " place before the run started, unchanged, and the runner saw "
            + ("it" if one else "them") + " fail: "
            + ("it is" if one else "they are") + " the proof of this fix. add"
            " a case only for a boundary or an error path "
            + ("it does" if one else "they do") + " not name.\n")
