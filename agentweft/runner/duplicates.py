"""new tests of a run that look alike, found at no model cost and handed to
the retro as a lead.

two new python tests of one file whose bodies, read as tokens with every
string and number counted as one kind of token, share at least 80% of the
tokens either one holds are in one group. a group is a lead, never a
finding: the retro reads the tests and decides whether they check one
behaviour and are one parametrized test. one file is one tier
(`testmap.tier_of`), so a unit test and an e2e test alike are never one
group: that is coverage at two levels.
"""
import ast
import io
import re
import textwrap
import tokenize
from pathlib import Path

from .testmap import tier_of

SIMILAR = 0.8
MOST = 8
STRINGS = tuple(getattr(tokenize, k) for k in
                ("STRING", "FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
                if hasattr(tokenize, k))


def tokens(source):
    """-> the set of tokens of python `source`, a string or number as one
    kind each, names and operators as written; empty when it does not
    tokenize."""
    out = set()
    try:
        for t in tokenize.generate_tokens(io.StringIO(source).readline):
            if t.type in STRINGS:
                out.add("<str>")
            elif t.type == tokenize.NUMBER:
                out.add("<num>")
            elif t.type in (tokenize.NAME, tokenize.OP):
                out.add(t.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return frozenset()
    return frozenset(out)


def bodies(text):
    """-> {name as a pytest id takes it after the file: the tokens of its
    body} for every test function and method of python source `text`, a
    docstring left out; {} when it does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    lines = text.splitlines()
    out = {}

    def visit(nodes, prefix):
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + "::")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("test"):
                body = node.body
                if len(body) > 1 and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    body = body[1:]
                said = textwrap.dedent("\n".join(
                    lines[body[0].lineno - 1:node.end_lineno]))
                out[prefix + node.name] = tokens(said)

    visit(tree.body, "")
    return out


def alike(one, other):
    """whether two token sets share at least SIMILAR of the tokens either
    holds."""
    if not one or not other:
        return False
    return len(one & other) >= SIMILAR * len(one | other)


def groups(place, ids):
    """-> [(tier, file, [test names])] for each group of two or more of the
    tests `ids` (pytest ids from the place) that are alike, in file order;
    a test that cannot be read is in none."""
    named = {}
    for i in ids:
        rel, _, name = str(i).partition("::")
        if name and rel.endswith(".py"):
            named.setdefault(rel, []).append(name.split("[")[0])
    out = []
    for rel in sorted(named):
        try:
            text = (Path(place) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = bodies(text)
        names = [n for n in dict.fromkeys(named[rel]) if found.get(n)]
        head = dict((n, n) for n in names)

        def top(n):
            while head[n] != n:
                n = head[n]
            return n

        for x, one in enumerate(names):
            for other in names[x + 1:]:
                if alike(found[one], found[other]):
                    head[top(other)] = top(one)
        kept = {}
        for n in names:
            kept.setdefault(top(n), []).append(n)
        out.extend((tier_of(rel), rel, g) for g in kept.values()
                   if len(g) > 1)
    return out


def lines(found):
    """-> one line per group, at most MOST, the rest counted."""
    out = ["- " + rel + " (" + tier + "): " + ", ".join(names)
           for tier, rel, names in found[:MOST]]
    if len(found) > MOST:
        out.append("- and " + str(len(found) - MOST) + " more groups")
    return out


def named_in(claim, rel, found):
    """-> the group of `found` in file `rel` that `claim` names two or more
    tests of, None for none."""
    for _, where, names in found:
        if where != rel:
            continue
        said = [n for n in names if re.search(
            r"(?<![\w])" + re.escape(n.split("::")[-1]) + r"(?![\w])",
            claim or "")]
        if len(said) > 1:
            return names
    return None
