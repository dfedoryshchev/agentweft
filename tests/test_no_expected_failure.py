"""the suite keeps no expected failure: a known gap is a floor stated in the
docs and pinned by a passing test of what the product does today, never a
test marked to fail.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = re.compile(r"\bmark\s*\.\s*" + "xfa" + r"il\b|\bpytest\s*\.\s*"
                    + "xfa" + r"il\s*\(")


def test_no_test_is_marked_to_fail():
    found = []
    for path in sorted(HERE.rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").split(
                "\n"), 1):
            if MARKER.search(line):
                found.append(path.relative_to(HERE).as_posix() + ":" + str(n))
    assert found == []


def test_the_marker_is_matched_and_the_bare_word_is_not():
    word = "xfa" + "il"
    assert MARKER.search("@pytest.mark." + word + "(strict=True)")
    assert MARKER.search("    pytest." + word + '("not yet")')
    assert not MARKER.search('@pytest.mark.parametrize("verb", ["skip", "'
                             + word + '"])')
