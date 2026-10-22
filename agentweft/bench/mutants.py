"""which tests a run added tell its fix apart from small breaks of it.

after a run, the source it changed is broken on purpose over the changed lines
only: the fix taken out whole (unpatch), each hunk of it taken out on its own,
and up to MOST small edits read off the syntax tree of the changed lines (a
comparison flipped, a number one up or down, a condition negated, a statement
deleted, two statements swapped). every new test runs against every mutant,
and the mutants a test fails on are its kill signature.

the tests the project already had run against every mutant too: a mutant
one of them kills is one the suite caught already, so a new test's unique
kills are only the mutants nothing in the suite it joined kills.

tests with the same signature likely guard the same thing: sixteen tests
that all die on one deleted line are one test written sixteen times. with
fewer than MINIMUM mutants that some test kills, a shared signature is only
a lead, and is reported as not enough mutants to judge. nothing is deleted or
skipped. a test green without the fix that kills nothing is a pin. a test red with the fix kills
nothing that can be read and is listed apart.

no model is asked; the same place gives the same mutants in the same order.
"""
import ast
import difflib
import os
import random
import shutil
import tempfile
import time
from pathlib import Path

from agentweft.guardrails import snapshot
from agentweft.guardrails.gates.base import fresh_python

from . import scorer

# how alike two signatures are (shared kills over all kills) to count as one
DUPLICATE_AT = 1.0
MOST = 20
# below this many mutants a shared signature is a lead, not a duplicate:
# two different tests can kill the same few mutants by chance
MINIMUM = 8
SEED = 0
# a mutant's run may take this many times the fixed run, and no less than
# TIMEOUT seconds, before it counts as killed: a deleted `i += 1` never ends
SLOWER = 5
TIMEOUT = 30
UNPATCH = "unpatch"
FLIP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
        ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn,
        ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
SIMPLE = (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr, ast.Return,
          ast.Raise, ast.Assert, ast.Delete)
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def files(root):
    """-> {path: text} for every python file under `root`."""
    root = Path(root)
    out = {}
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if any(part in snapshot.SKIP_DIRS for part in rel.parts):
            continue
        rel = rel.as_posix()
        out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


def sources(start, place):
    """-> [(path, before or None, after or None)] for the source files, not
    the tests, that the run added, removed or changed."""
    was, now = files(start), files(place)
    return [(rel, was.get(rel), now.get(rel))
            for rel in sorted(set(was) | set(now))
            if not snapshot.is_test(rel) and was.get(rel) != now.get(rel)]


def hunks(before, after):
    """-> the difflib opcodes that are not equal, over lines."""
    a = (before or "").splitlines(True)
    b = (after or "").splitlines(True)
    return a, b, [op for op in difflib.SequenceMatcher(None, a, b,
                                                       autojunk=False)
                  .get_opcodes() if op[0] != "equal"]


def changed_lines(before, after):
    """-> the 1-based lines of `after` that are new or not as they were."""
    _, _, ops = hunks(before, after)
    return {n + 1 for _, _, _, j1, j2 in ops for n in range(j1, j2)}


def reverts(rel, before, after):
    """-> [(name, text)] with each hunk of the change taken out alone."""
    a, b, ops = hunks(before, after)
    out = []
    for _, i1, i2, j1, j2 in ops:
        text = "".join(b[:j1] + a[i1:i2] + b[j2:])
        out.append(("hunk " + rel + ":" + str(j1 + 1), text))
    return out


def offsets(data):
    """-> the offset in `data` where each 1-based line starts."""
    out, at = [0, 0], 0
    for line in data.splitlines(True):
        at += len(line)
        out.append(at)
    return out


def span(starts, node):
    return (starts[node.lineno] + node.col_offset,
            starts[node.end_lineno] + node.end_col_offset)


def splice(data, starts, node, new):
    a, b = span(starts, node)
    return (data[:a] + new.encode("utf-8") + data[b:]).decode("utf-8")


def edits(text, lines):
    """-> [(line, col, kind, text)] for each small edit of a node that starts
    on one of `lines`."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    # ast columns count utf-8 bytes, so a line with a non-ascii character
    # before the node would be cut in the wrong place as a str
    text = text.encode("utf-8")
    starts = offsets(text)
    out = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if isinstance(body, list):
                out.extend(statements(text, starts, body, lines))
        if getattr(node, "lineno", None) not in lines:
            continue
        here = (node.lineno, node.col_offset)
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in FLIP:
                    flipped = ast.Compare(node.left, list(node.ops),
                                          node.comparators)
                    flipped.ops[i] = FLIP[type(op)]()
                    out.append(here + ("flip " + str(i + 1), splice(
                        text, starts, node, ast.unparse(flipped))))
        elif (isinstance(node, ast.Constant) and type(node.value) is int):
            for d, sign in ((1, "+1"), (-1, "-1")):
                out.append(here + ("const " + sign, splice(
                    text, starts, node, str(node.value + d))))
        if isinstance(node, (ast.If, ast.While, ast.IfExp)):
            a, b = span(starts, node.test)
            out.append((node.test.lineno, node.test.col_offset, "negate",
                        (text[:a] + b"not (" + text[a:b] + b")"
                         + text[b:]).decode("utf-8")))
    return out


def statements(text, starts, body, lines):
    """-> the deletes and swaps of the statements in one block."""
    out = []
    for i, s in enumerate(body):
        doc = isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
        if (s.lineno in lines and not isinstance(s, DEFS + (ast.Pass,))
                and not doc):
            out.append((s.lineno, s.col_offset, "delete",
                        splice(text, starts, s, "pass")))
        if i + 1 == len(body):
            continue
        t = body[i + 1]
        if not (isinstance(s, SIMPLE) and isinstance(t, SIMPLE)):
            continue
        if s.lineno not in lines and t.lineno not in lines:
            continue
        a, mid = span(starts, s)
        gap, b = span(starts, t)
        swapped = (text[:a] + text[gap:b] + text[mid:gap] + text[a:mid]
                   + text[b:])
        out.append((s.lineno, s.col_offset, "swap " + str(t.lineno),
                    swapped.decode("utf-8")))
    return out


def build(start, place, seed=SEED, most=MOST):
    """-> [{"name", "files": {path: text or None}}], the unpatch first, then
    each hunk taken out, then the small edits: all of them up to `most`, a
    seeded pick of `most` past that. a mutant that reads the same as the fix
    or as one before it is dropped. None is a file the mutant removes."""
    changed = sources(start, place)
    if not changed:
        return []
    out = [{"name": UNPATCH, "files": {rel: was for rel, was, _ in changed}}]
    small = []
    for rel, was, now in changed:
        for name, text in reverts(rel, was, now):
            out.append({"name": name, "files": {rel: text}})
        if now is None:
            continue
        for line, col, kind, text in sorted(
                edits(now, changed_lines(was, now)), key=lambda e: e[:3]):
            small.append({"name": rel + ":" + str(line) + ":" + str(col)
                          + " " + kind, "files": {rel: text}})
    fixed = {rel: now for rel, _, now in changed}
    out = distinct(out, fixed)
    small = distinct(out + small, fixed)[len(out):]
    if len(small) > most:
        keep = set(random.Random(seed).sample(range(len(small)), most))
        small = [m for i, m in enumerate(small) if i in keep]
    return out + small


def distinct(made, fixed):
    """-> `made` without the mutants that change nothing, do not parse, or
    read the same as one before them."""
    seen = {tuple(sorted(fixed.items(), key=lambda kv: kv[0]))}
    out = []
    for m in made:
        key = tuple(sorted({**fixed, **m["files"]}.items(),
                           key=lambda kv: kv[0]))
        if key in seen or not parses(m["files"]):
            continue
        seen.add(key)
        out.append(m)
    return out


def parses(texts):
    for text in texts.values():
        if text is None:
            continue
        try:
            ast.parse(text)
        except (SyntaxError, ValueError):
            return False
    return True


def new_tests(start, place):
    """-> the ids of the tests the run added or changed, the same way the
    red-first gate reads them: by name and code, file by file."""
    was, now = files(start), files(place)
    out = []
    for rel in sorted(now):
        if not snapshot.is_test(rel) or was.get(rel) == now[rel]:
            continue
        found = snapshot.test_ids(now[rel], rel)
        if found is None:
            out.append(rel)
            continue
        had = snapshot.test_ids(was.get(rel) or "", rel) or {}
        out.extend(i for i, code in found.items() if had.get(i) != code)
    return out


def old_tests(start, place):
    """-> the ids of the tests the place holds as the project started with
    them: the suite the run's new tests joined."""
    was, now = files(start), files(place)
    out = []
    for rel in sorted(now):
        if not snapshot.is_test(rel) or rel not in was:
            continue
        found = snapshot.test_ids(now[rel], rel)
        if found is None:
            if was[rel] == now[rel]:
                out.append(rel)
            continue
        had = snapshot.test_ids(was[rel], rel) or {}
        out.extend(i for i, code in found.items() if had.get(i) == code)
    return out


def run(place, mutant, tests, limit=None):
    """-> {case: passed} for `tests` on a copy of `place` with `mutant`'s
    files laid over it. a run past `limit` seconds is {}: every case
    killed, the way a mutant that never ends is caught."""
    with tempfile.TemporaryDirectory(prefix="bench-mutant-",
                                     ignore_cleanup_errors=True) as tmp:
        here = Path(tmp) / "repo"
        shutil.copytree(str(place), str(here), ignore=scorer.SKIP)
        for rel, text in ((mutant or {}).get("files") or {}).items():
            target = here / rel
            if text is None:
                if target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        # the tests import the project from the copy, never from an
        # editable install of the person's own tree
        path = [str(here)] + ([os.environ["PYTHONPATH"]]
                              if os.environ.get("PYTHONPATH") else [])
        with fresh_python({"PYTHONPATH": os.pathsep.join(path)}) as env:
            got = {}
            for ids in by_file(tests):
                said = scorer.pytest(here, ids, env=env,
                                     timeout=limit or scorer.TIMEOUT)
                if any(k.startswith("::timed out") for k in said):
                    return {}
                got.update(said)
            return got


def by_file(tests):
    """-> the test ids grouped by their file, one pytest each: a node id in
    a file that cannot be imported ends the whole session, so a mutant that
    breaks one file's import would kill every other file's tests too."""
    out = {}
    for t in tests:
        out.setdefault(t.split("::")[0], []).append(t)
    return [out[f] for f in sorted(out)]


def similar(a, b):
    a, b = set(a), set(b)
    return len(a & b) / float(len(a | b)) if a | b else 1.0


def groups(kills, at=DUPLICATE_AT):
    """-> the tests that kill something, grouped: each joins the first group
    whose first test's signature is at least `at` alike to its own."""
    out = []
    for t in sorted(kills):
        if not kills[t]:
            continue
        for g in out:
            if similar(kills[g[0]], kills[t]) >= at:
                g.append(t)
                break
        else:
            out.append([t])
    return out


def score(start, place, seed=SEED, most=MOST, at=DUPLICATE_AT,
          least=MINIMUM):
    """-> each new test's kill signature over the mutants of the fix, the
    likely duplicate groups, the pins and the tests red with the fix. with
    fewer than `least` mutants the shared signatures are `undecided`, never
    duplicates. nothing is removed or skipped: the report only labels."""
    made = build(start, place, seed, most)
    tests = new_tests(start, place)
    suite = old_tests(start, place)
    out = {"mutants": [m["name"] for m in made], "duplicate_at": at,
           "minimum": least, "tests": {}, "signatures": 0,
           "duplicates": [], "undecided": [], "pins": [],
           "red_with_fix": [], "files": sorted({rel for m in made
                                               for rel in m["files"]}),
           "suite": 0, "suite_kills": [], "unique": {}, "unique_kills": 0}
    if not made or not tests:
        return out
    began = time.time()
    fixed = run(place, None, tests)
    ran = run(place, None, suite) if suite else {}
    limit = max(TIMEOUT, SLOWER * (time.time() - began))
    joined = sorted(c for c, ok in ran.items() if ok)
    green = sorted(c for c, ok in fixed.items() if ok)
    out["red_with_fix"] = sorted(c for c, ok in fixed.items() if not ok)
    if not green:
        return out
    seen = dict((m["name"], run(place, m, tests + suite, limit))
                for m in made)
    kills = dict((c, [m["name"] for m in made if not seen[m["name"]].get(c)])
                 for c in green)
    made_already = sorted({m["name"] for m in made for c in joined
                           if not seen[m["name"]].get(c)})
    unique = dict((c, [m for m in kills[c] if m not in made_already])
                  for c in green)
    out.update({"suite": len(joined), "suite_kills": made_already,
                "unique": unique,
                "unique_kills": len({m for c in green for m in unique[c]})})
    found = groups(kills, at)
    shared = [g for g in found if len(g) > 1]
    # a mutant nothing kills (a dead line deleted) cannot tell two tests
    # apart, so it does not count toward the minimum
    judged = len({m for c in green for m in kills[c]})
    enough = judged >= least
    out.update({"tests": kills, "signatures": len(found), "judged": judged,
                "duplicates": shared if enough else [],
                "undecided": [] if enough else shared,
                "pins": [c for c in green if not kills[c]
                         and seen.get(UNPATCH, {}).get(c)]})
    return out


def lines(got):
    """-> the report's lines for one run, one item per line."""
    if not got["mutants"]:
        return ["mutants: no source line changed, nothing to mutate"]
    out = ["mutants " + str(len(got["mutants"])) + " over "
           + ", ".join(got["files"]) + ", "
           + str(len(got["tests"]) + len(got["red_with_fix"]))
           + " new tests",
           "  duplicate threshold " + str(got["duplicate_at"]),
           "  minimum to judge " + str(got["minimum"]) + " mutants",
           "  distinct signatures " + str(got["signatures"])]
    if got["undecided"]:
        out.append("  not enough mutants to judge, "
                   + str(got.get("judged", len(got["mutants"]))) + " of "
                   + str(got["minimum"]) + ": shared signatures are leads")
        for g in got["undecided"]:
            out.append("    " + str(len(g)) + " tests share a signature")
            out.extend("      " + t for t in g)
    else:
        out.append("  likely duplicate groups " + str(len(got["duplicates"])))
    for g in got["duplicates"]:
        out.append("    " + str(len(g)) + " tests, one signature")
        out.extend("      kills " + m for m in got["tests"][g[0]])
        out.extend("      " + t for t in g)
    if got["tests"]:
        out.append("  the suite it joined kills "
                   + str(len(got.get("suite_kills", []))) + " of "
                   + str(len(got["mutants"])) + " mutants with "
                   + str(got.get("suite", 0)) + " tests; unique kills "
                   + str(got.get("unique_kills", 0)))
        none = [t for t in sorted(got.get("unique", {}))
                if got["tests"][t] and not got["unique"][t]]
        out.append("  no kill of its own " + str(len(none)))
        out.extend("      " + t for t in none)
    out.append("  pins " + str(len(got["pins"])))
    out.extend("    " + t for t in got["pins"])
    out.append("  red with the fix " + str(len(got["red_with_fix"])))
    out.extend("    " + t for t in got["red_with_fix"])
    return out
