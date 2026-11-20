"""the tests already near a change are handed to the steps that write tests,
by tier and capped, so a case one of them checks is updated, never copied."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.runner import engine, prompts, resume, testmap

import test_test_edits as te

NL = chr(10)


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=NL)


def a_project(root, more=0):
    put(root, "pkg/__init__.py", "")
    put(root, "pkg/report.py", "def report(names):" + NL
        + "    return sorted(names)" + NL)
    put(root, "pkg/other.py", "X = 1" + NL)
    put(root, "tests/test_report.py", "from pkg.report import report" + NL
        + "".join(NL + "def test_case_" + str(n) + "():" + NL
                  + "    assert report([]) == []" + NL
                  for n in range(2 + more)))
    put(root, "tests/integration/test_cli_flow.py", "import pkg.report" + NL
        + NL + "class TestFlow:" + NL + "    def test_runs(self):" + NL
        + "        assert pkg.report.report(['b']) == ['b']" + NL)
    put(root, "tests/test_other.py", "from pkg import other" + NL + NL
        + "def test_x():" + NL + "    assert other.X" + NL)
    put(root, "web/report.test.js", "const r = require('../pkg/report');"
        + NL + "test('lists caf" + chr(0xE9) + "', () => {});" + NL)
    return root


def test_the_tests_near_a_named_file_are_listed_by_tier_nearest_first(
        tmp_path):
    root = a_project(tmp_path / ("caf" + chr(0xE9)))
    said = testmap.lines(testmap.near(root, ["fix pkg\\report.py: it drops"
                                             " a name"]))
    assert said == [
        testmap.HEAD, "unit:",
        "- tests/test_report.py::test_case_0",
        "- tests/test_report.py::test_case_1",
        "- web/report.test.js::lists caf" + chr(0xE9),
        "integration:",
        "- tests/integration/test_cli_flow.py::TestFlow::test_runs"]
    assert testmap.as_prompt(root, ["pkg/report.py"]).startswith(
        NL + NL + testmap.HEAD + NL)


@pytest.mark.parametrize("texts", [[], [""], ["the report is wrong"],
                                   ["tests/test_report.py"],
                                   ["pkg/missing.py"]])
def test_no_named_product_file_hands_no_tests(tmp_path, texts):
    root = a_project(tmp_path)
    assert testmap.as_prompt(root, texts) == ""
    assert testmap.as_prompt(None, ["pkg/report.py"]) == ""


def test_the_list_is_capped_and_what_is_left_out_named_by_file(tmp_path):
    root = a_project(tmp_path, more=48)
    said = testmap.lines(testmap.near(root, ["pkg/report.py"]))
    listed = [l for l in said if l.startswith("- ")]
    assert 20 <= len(listed) <= testmap.MOST
    assert len("\n".join(said[:-1])) <= testmap.CAP
    assert said[-1].startswith("more tests left out at the cap, open them"
                               " yourself: tests/test_report.py (")
    assert "tests/integration/test_cli_flow.py (1)" in said[-1]


def test_a_test_writing_step_is_handed_the_map_and_a_plan_step_is_not(
        tmp_path, monkeypatch):
    place = te.a_place(tmp_path / "repo")
    te.a_flow(tmp_path, "build", te.TESTER + te.WORKER)
    put(tmp_path, "flows/build/tester.md", "# tester" + NL + NL + "{TASK}"
        + NL)
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.setdefault(step, prompt)
        if step == "tester.md":
            (place / "tests" / "test_report.py").write_text(
                te.module(te.RIGHT, te.COUNT), encoding="utf-8")
            return te.TESTER_SAID, False
        (place / "report.py").write_text(te.COUNTED, encoding="utf-8")
        return te.WORKER_SAID, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "build", "--force",
                                      "--workdir", str(place), "--task",
                                      "count the names in report.py"])
    assert engine.main() == 0
    assert testmap.HEAD + NL + "unit:" + NL \
        + "- tests/test_report.py::test_alphabetical" + NL in sent["tester.md"]
    assert testmap.HEAD not in sent["worker.md"]
    handoff = te.read(te.folders()[-1] / "handoff.md").split(NL)
    assert ("tests: added 1 to files the run started with / added 0 in new"
            " files / changed 0 the run started with / in files"
            " tests/test_report.py.") in handoff[:8], handoff[:8]


def test_a_test_writing_step_is_prompted_before_any_product_line_exists(
        tmp_path, monkeypatch):
    from agentweft.runner import gating
    from agentweft.runner import run as running

    place = te.a_place(tmp_path / "repo")
    te.a_flow(tmp_path, "build", te.TESTER + te.WORKER)
    seen = {}
    step = running.Run.step

    def spy(self, name, *args, **kwargs):
        seen[name] = sorted(gating.added_since_start(self) or {})
        return step(self, name, *args, **kwargs)

    monkeypatch.setattr(running.Run, "step", spy)
    code, _ = te.running(tmp_path, monkeypatch, place,
                         te.writes_of(te.module(te.RIGHT, te.COUNT)), False)
    assert code == 0
    assert seen == {"tester.md": [], "worker.md": ["tests/test_report.py"]}


PROOF = "is the proof of this fix"
GIVEN = "tests/test_report.py::test_alphabetical"
RED_SAID = "FAILS: assert ['a', 'b'] == ['b', 'a']" + NL + "TEST: " + GIVEN \
    + NL
PATCHER = ("  - role: patcher" + NL + "    prompt: worker.md" + NL
           + "    writes: product" + NL + "    writes_tests: true" + NL
           + "    gates:" + NL + "      - gate: red-first" + NL
           + "        command: [\"python\", \"-m\", \"pytest\", \"-q\", \"-p\","
           " \"no:cacheprovider\", \"--junitxml={results}\", \"{test}\"]" + NL
           + "        results: junit" + NL)


def patcher_prompt(tmp_path, monkeypatch, said, writes, *args):
    """-> the prompt the patcher was sent after the step holding the red
    test answered `said` and wrote `writes`, on a place whose start test
    test_alphabetical fails."""
    place = te.a_place(tmp_path / "repo", baseline=te.WRONG)
    te.a_flow(tmp_path, "build", te.TESTER + PATCHER)
    put(tmp_path, "flows/build/tester.md", "# tester" + NL + NL + "{TASK}"
        + NL)
    sent = {}

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        sent.setdefault(step, prompt)
        if step == "tester.md":
            for rel, text in writes.items():
                put(place, rel, text)
            return said, False
        return te.WORKER_SAID, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "build", "--force",
                                      "--workdir", str(place), "--task",
                                      "report.py lists names unsorted"]
                        + list(args))
    engine.main()
    assert "worker.md" in sent, sent
    return sent["worker.md"]


@pytest.mark.parametrize("said,writes,args,told", [
    (RED_SAID, {}, (), True),
    (te.TESTER_SAID, {"tests/test_report.py": te.module(te.WRONG, te.COUNT)},
     (), False),
    (te.APART_SAID, {"tests/test_count.py": te.HEAD + NL + NL + te.COUNT},
     (), False),
    (RED_SAID, {}, ("--skip", "tests", "hotfix"), False)],
    ids=["a start test proven red", "a test added to a start file",
         "a new test file", "tests skipped, no gate ran"])
def test_only_a_supplied_red_proof_tells_the_patcher_its_test_is_the_proof(
        tmp_path, monkeypatch, said, writes, args, told):
    prompt = patcher_prompt(tmp_path, monkeypatch, said, writes, *args)
    assert (PROOF in prompt) is told
    assert (testmap.supplied([GIVEN]) in prompt) is told


def test_the_supplied_line_names_every_test_and_none_for_no_test():
    assert testmap.supplied([]) == ""
    one = testmap.supplied([GIVEN])
    two = testmap.supplied([GIVEN, "tests/test_report.py::test_more"])
    assert GIVEN in one and "the test you were given" in one
    assert "test_more" in two and "the tests you were given" in two


def test_the_tests_line_counts_new_files_apart():
    from agentweft.runner import summary

    assert summary.tests_line({}) == ""
    assert summary.tests_line({"test_ids": {
        "tests/test_a.py": ["tests/test_a.py::test_x"],
        "tests/test_b.py": ["tests/test_b.py::test_y",
                            "tests/test_b.py::test_z"]},
        "tests_new": ["tests/test_b.py"]}) == (
        "tests: added 1 to files the run started with / added 2 in new"
        " files / changed 0 the run started with / in files tests/test_a.py,"
        " tests/test_b.py.")
