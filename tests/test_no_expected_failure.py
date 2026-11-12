"""the suite keeps no expected failure: a known gap is a floor stated in the
docs and pinned by a passing test of what the product does today, never a
test marked to fail.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORD = "xfa" + "il"
GAP = r"[\s\\]*"
MARKER = re.compile(r"\bmark" + GAP + r"\." + GAP + WORD + r"\b|\bpytest"
                    + GAP + r"\." + GAP + WORD + GAP + r"\(|\badd_marker"
                    + GAP + r"\(" + GAP + r"[\"']" + WORD + r"[\"']")
IMPORTED = re.compile(r"\bfrom\s+pytest\s+import\s+\(?[\w\s,]*\b" + WORD
                      + r"\b")
BARE = re.compile(r"(?<![\w.])" + WORD + r"\s*\(")


def marked(text):
    """-> the lines of `text` a marker to fail starts on: the mark, the
    call, the marker named as a string, or the bare call once the file
    imports it from pytest, a marker split across lines included."""
    found = [m.start() for m in MARKER.finditer(text)]
    if IMPORTED.search(text):
        found += [m.start() for m in BARE.finditer(text)]
    return sorted({text.count("\n", 0, at) + 1 for at in found})


def test_no_test_is_marked_to_fail():
    found = []
    for path in sorted(HERE.rglob("*.py")):
        for n in marked(path.read_text(encoding="utf-8")):
            found.append(path.relative_to(HERE).as_posix() + ":" + str(n))
    assert found == []


def test_the_marker_is_matched_and_the_bare_word_is_not():
    assert marked("@pytest.mark." + WORD + "(strict=True)")
    assert marked("    pytest." + WORD + '("not yet")')
    assert not marked('@pytest.mark.parametrize("verb", ["skip", "'
                      + WORD + '"])')


def test_every_spelling_of_the_marker_is_matched():
    assert marked('request.node.add_marker("' + WORD + '")') == [1]
    assert marked("request.node.add_marker(pytest.mark." + WORD + ")") == [1]
    assert marked("from pytest import " + WORD + "\n\n\ndef test_x():\n"
                  "    " + WORD + '("not yet")\n') == [5]
    assert marked("from pytest import (raises,\n    " + WORD + ")\n"
                  "    " + WORD + "()\n") == [3]
    assert marked("@pytest.mark.\\\n    " + WORD + "\ndef test_x():\n") == [1]
    assert marked("@(pytest.mark\n  ." + WORD + ")\n") == [1]
    assert not marked("def " + WORD + "s(): pass\nx = " + WORD + "_count()\n")
    assert not marked(WORD + "(1)\n")
