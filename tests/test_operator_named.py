"""the human who answers a run that waits is named "the operator" in every
line the runner prints, records or teaches a step, and hands a question
back with `you decide`.

the section and outcome words `needs you` and `assumed - tell me if wrong`
stay: they head sections and journal lines that readers parse. a line that
speaks to the step itself as "you" is not a name for the operator.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.orchestrate import park
from agentweft.runner import ruling

ROOT = Path(__file__).resolve().parent.parent
OTHER_NAMES = re.compile(r"\b(the person|a person|person's|yours|for you|"
                         r"your ruling|your hand-back)\b", re.I)
# a taught line may give the step its own work as "yours"; it may not name
# the operator another way or teach the old hand-back word
TAUGHT_NAMES = re.compile(r"\b(the person|a person|person's|your ruling|"
                          r"your hand-back|starts yours|yours to overrule|"
                          r"yours to stage|yours to review)\b|`yours", re.I)
TAUGHT = (["agentweft/fragments", "agentweft/roles/library",
           "agentweft/skills", "flows", "docs"])
# the old hand-back word, still read so answers already given replay
ALLOWED = {("agentweft/runner/ruling.py", "yours")}
# a model's words the no-recommendation rule reads; a reader of release
# notes; the author of the tool
NOT_THE_OPERATOR = ("The person names a date", "a person would read",
                    "one person's tool")


def docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            out.add(id(node.body[0].value))
    return out


def printed():
    for path in sorted((ROOT / "agentweft").rglob("*.py")):
        name = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in skip \
                    and (name, node.value) not in ALLOWED:
                yield name + ":" + str(node.lineno), node.value


def taught():
    paths = [ROOT / "README.md"]
    for top in TAUGHT:
        paths += sorted(p for p in (ROOT / top).rglob("*")
                        if p.suffix in (".md", ".yaml") and p.is_file())
    for path in paths:
        for n, line in enumerate(
                path.read_text(encoding="utf-8").split("\n"), 1):
            yield path.relative_to(ROOT).as_posix() + ":" + str(n), line


def test_no_printed_or_taught_line_names_the_operator_another_way():
    found = [where + ": " + text[:120] for where, text in printed()
             if OTHER_NAMES.search(text)]
    found += [where + ": " + text[:120] for where, text in taught()
              if TAUGHT_NAMES.search(text) and not any(
                  words in text for words in NOT_THE_OPERATOR)]
    assert found == [], "\n".join(found)


def test_the_park_text_speaks_of_the_operator_never_to_you():
    for led in (False, True):
        for edits in (False, True):
            text = "\n".join(park.ruling(
                "planner.md", "a ruling", [("planner.md", 3)], ["worker.md"],
                "python run.py led --resume x", "NEEDS: which code?",
                led=led, edits=edits))
            spoken = text.replace(ruling.YOU_DECIDE, "")
            assert not re.search(r"\byour?\b", spoken, re.I), text
            assert "yours" not in text


def test_a_park_of_a_led_flow_offers_you_decide():
    text = "\n".join(park.ruling("planner.md", "a ruling", [], [], "go",
                                 "NEEDS: which code?", led=True))
    assert 'go --answer "you decide"' in text.split("\n")[-1], text


@pytest.mark.parametrize("answer", [
    "you decide", "You decide", "YOU DECIDE", "you decide.", "you decide:",
    "you decide: escape it", "  you decide", "you decide\r\n",
    "you  decide, as you see fit", "you decide - " + chr(0x0444) + chr(0x0430),
    "you\tdecide", "yours: make the call yourself", "Yours: return 304"])
def test_an_answer_that_opens_with_you_decide_hands_the_call_back(answer):
    assert ruling.handed_back(answer)


@pytest.mark.parametrize("answer", [
    "", None, "   ", "you decided earlier that 200 is right",
    "```\nyou decide\n```", "ok, you decide", "you decides", "you decide_it",
    "yourself", "decide it yourself", "if you decide, say so",
    "you, decide"])
def test_an_answer_that_does_not_open_with_you_decide_hands_nothing_back(
        answer):
    assert not ruling.handed_back(answer)
