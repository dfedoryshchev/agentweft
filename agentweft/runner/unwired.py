"""new code a run added that nothing in the product calls.

a new function or class that only a test calls, or nothing does, is either a
feature written and never wired in or a new entry point a library hands its
users; the suite passes on both. the handoff names each one with the step
that wrote it, so the person reading it tells which.

python only: a `def` or `class` line the run added to a `.py` file that is
not a test. a reference is the name as a whole word in the product's python,
its own def line left out, so a common name can hide one: what is named is a
floor, never the whole of it.
"""
import re

DEF = re.compile(r"^\s*(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)")
LINE = "- not called from the product: "


def found(added, product, tests):
    """-> [{"path", "line", "kind", "name", "tests"}] for each def or class
    the run added that no product file refers to but by its own def line.
    `added` is {path: [(line number, the line)]}, the lines the run added to
    product python files; `product` and `tests` are {path: text} for every
    python file as it is now. `tests` says whether a test refers to it."""
    out = []
    for path in sorted(added):
        for number, text in added[path]:
            m = DEF.match(text)
            if not m:
                continue
            name = m.group(2)
            if name.startswith("__") and name.endswith("__"):
                continue
            word = re.compile(r"\b" + re.escape(name) + r"\b")
            if len(word.findall(product.get(path, ""))) > 1 or any(
                    word.search(t) for p, t in product.items() if p != path):
                continue
            out.append({"path": path, "line": number, "kind": m.group(1),
                        "name": name,
                        "tests": any(word.search(t) for t in tests.values())})
    return out


def lines(found, by):
    """-> a handoff line per def `found`, ending with the steps that wrote
    its file when `by` ({path: [steps]}) knows them."""
    out = []
    for f in found:
        who = by.get(f["path"]) or []
        out.append(LINE + f["path"] + ":" + str(f["line"]) + " " + f["kind"]
                   + " " + f["name"] + ", "
                   + ("only tests call it" if f["tests"] else "nothing calls it")
                   + (" (" + ", ".join(who) + ")" if who else ""))
    return out
