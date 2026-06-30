import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.evals import harness


def test_the_digest_has_cases():
    names = [p.name for p in harness.cases_for("weekly-digest")]
    assert "quiet-week" in names
    assert "busy-week" in names


def test_a_case_knows_where_its_inputs_are():
    case = harness.load_case(harness.cases_for("weekly-digest")[0])
    assert case["inbox"].exists()


def test_scoring_counts_only_what_can_be_checked():
    spec = runner.config("weekly-digest")
    good = ("## what changed" + chr(10) + "- a.md | changed | x" + chr(10)
            + chr(10) + "## needs me" + chr(10) + "- b.md | needs-me | y" + chr(10))
    r = harness.score(spec, good)
    assert r["checked"] >= 1
    assert r["passed"] == r["checked"]


def test_a_broken_promise_is_counted_as_broken():
    spec = runner.config("weekly-digest")
    bad = ("## what changed" + chr(10) + "- a.md | changed | x" + chr(10)
           + chr(10) + "## can wait" + chr(10) + "- a.md | can-wait | again" + chr(10))
    r = harness.score(spec, bad)
    assert r["passed"] < r["checked"]
