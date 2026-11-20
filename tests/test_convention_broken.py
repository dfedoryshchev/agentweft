"""a convention the run's own check reads broken is handed to the step that
owns the folder and stays on the head until fixed or ticketed.

a fact's check runs after a step that changed a file in its scope. when it
reads broken, the line it matched is named on the head among the questions,
with the step of the flow that writes that file: the run's own record says the
folder breaks the project's rule, and a line read by no step is a line read by
no one. a later check of the same fact that holds takes it off the head (it was
fixed); a nice-to-do the retro keeps on the matched file takes it off too (it
is ticketed). the step that writes the folder is handed the breach on its next
go in the run.
"""
import sys
import types

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.runner import engine, gating, summary
from test_fact_check import entry, put
from test_stops import a_flow, the_folder

NL = chr(10)

# two breaches as a measured record shows them: a `print(` left at
# pantry/services/units.py:57 against F-0051, and a bare error string left at
# pantry/api/locations.py:30 against F-0050
SHAPES = {
    "F-0051": ("pantry/services/", 'grep -rn -F "print(" pantry/services'
               " exits 1", "pantry/services/units.py", 57,
               '    print("clean_unit: trimmed %r" % unit)',
               "pantry/services/items.py"),
    "F-0050": ("pantry/api/", 'grep -rnE "\\"error\\": *\\"" pantry/api exits'
               " 1", "pantry/api/locations.py", 30,
               '        return respond.send(start_response, 400, {"error":'
               ' "name is required"})', "pantry/api/items.py"),
}


def a_place(tmp_path, id):
    scope, check, rel, n, line, touched = SHAPES[id]
    put(tmp_path, rel, NL.join(["x = 1"] * (n - 1) + [line, ""]))
    put(tmp_path, touched, "def get():" + NL + "    return 1" + NL)
    put(tmp_path, "facts/" + scope + "_folder.md",
        entry(id, scope, check, claim="the folder keeps its rule"))
    return scope, check, rel, n, touched


def flow(tmp_path, monkeypatch, steps):
    """`steps` is (role, {file: text}) per step, each writing product code."""
    replies = ["provider:", "  provider: fake", "  replies:"]
    for role, writes in steps:
        replies.extend(["    " + role + ".md:", "      - say: |",
                        "          changed it"])
        if writes:
            replies.append("        writes:")
        for rel, text in writes.items():
            replies.append("          " + rel + ": |")
            replies.extend("            " + l for l in text.split(NL)[:-1])
    a_flow(tmp_path, monkeypatch, "facts",
           [role + NL + "writes: product" for role, _ in steps],
           tail=NL.join(replies) + NL,
           args=("--skip-tests", "the place has no tests"))


def head_of(folder):
    lines = (folder / "handoff.md").read_text(encoding="utf-8").split(NL)
    first = lines.index("## the one decision") + 1
    end = next(n for n in range(first, len(lines))
               if lines[n].startswith("## "))
    return NL.join(lines[first:end])


@pytest.mark.parametrize("id", sorted(SHAPES))
def test_a_convention_the_run_s_check_reads_broken_is_on_the_head(
        tmp_path, monkeypatch, id):
    scope, check, rel, n, touched = a_place(tmp_path, id)
    flow(tmp_path, monkeypatch, [("worker", {
        touched: "def get():" + NL + "    return 2" + NL})])
    assert engine.main() == 0
    head = head_of(the_folder())
    assert ("- a convention the run's own check reads broken: " + id + " on "
            + scope + ": the folder keeps its rule") in head
    assert ("  at " + rel + ":" + str(n) + " (" + check + "); handed to"
            " worker.md, which writes it") in head
    assert "nothing waits on you" not in head


def test_a_breach_a_later_check_reads_held_is_off_the_head(tmp_path,
                                                            monkeypatch):
    scope, check, rel, n, touched = a_place(tmp_path, "F-0051")
    flow(tmp_path, monkeypatch, [
        ("worker", {touched: "def get():" + NL + "    return 2" + NL}),
        ("patcher", {rel: "x = 1" + NL})])
    assert engine.main() == 0
    head = head_of(the_folder())
    assert "a convention the run's own check reads broken" not in head
    assert "nothing waits on you" in head


def test_the_step_that_writes_the_folder_is_handed_the_breach():
    said = ('grep exits 0, the fact says 1: pantry/services/units.py:57:'
            '    print("x")')
    run = types.SimpleNamespace(
        breaches={"F-0051": {"fact": "F-0051", "scope": ["pantry/services/"],
                             "claim": "no print", "check": "grep ...",
                             "result": "broken", "said": said}},
        writes_for=lambda step: {"worker.md": "product",
                                 "tester.md": "tests"}.get(step, ""))
    brief = gating.breach_brief(run, "worker.md")
    assert "F-0051 on pantry/services/: no print" in brief
    assert "pantry/services/units.py:57" in brief
    assert gating.breach_brief(run, "tester.md") == ""
    assert gating.breach_brief(run, "reviewer.md") == ""
    assert gating.breach_brief(types.SimpleNamespace(), "worker.md") == ""


def test_a_breach_with_no_line_matched_is_owned_by_its_scope():
    run = types.SimpleNamespace(
        breaches={"F-0002": {"fact": "F-0002", "scope": ["tests/"],
                             "claim": "each test file imports pytest",
                             "check": "grep ...", "result": "broken",
                             "said": "grep exits 1, the fact says 0"}},
        writes_for=lambda step: {"tester.md": "tests"}.get(step, ""))
    assert "F-0002" in gating.breach_brief(run, "tester.md")


HEAD = NL.join(["# f r: done", "", "## the one decision",
                "- a convention the run's own check reads broken: F-0051 on"
                " pantry/services/: no print",
                "  at pantry/services/units.py:57 (grep ...); handed to"
                " worker.md, which writes it; recommendation: fix the line so"
                " the check holds, or keep a ticket on"
                " pantry/services/units.py", "", "## why", "- x", ""])


def test_a_breach_the_retro_tickets_on_its_file_leaves_the_head(tmp_path):
    path = tmp_path / "handoff.md"
    path.write_text(HEAD, encoding="utf-8")
    summary.after_retro(path, [{"step": "retro.md", "facts": {}}], "$0",
                        ticketed=["pantry/services/units.py"])
    head = head_of(tmp_path)
    assert "F-0051" not in head
    assert "nothing waits on you" in head


def test_a_ticket_on_another_file_leaves_the_breach_on_the_head(tmp_path):
    path = tmp_path / "handoff.md"
    path.write_text(HEAD, encoding="utf-8")
    summary.after_retro(path, [{"step": "retro.md", "facts": {}}], "$0",
                        ticketed=["pantry/services/items.py"])
    assert "F-0051" in head_of(tmp_path)
