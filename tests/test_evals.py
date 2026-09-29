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


def test_a_case_pins_its_provider():
    case = harness.load_case(harness.cases_for("weekly-digest")[0])
    assert case["provider"] == {"provider": "fake"}


def test_the_case_provider_beats_the_flows():
    """the whole point of an eval is that it is repeatable and free. the flow
    it runs says cli, and on the merge step it says cli again."""
    from agentweft.runner.engine import Run

    spec = runner.config("weekly-digest")
    run = Run("weekly-digest", spec, {}, provider={"provider": "fake"})
    assert run.provider.name == "fake"
    assert [p.name for p in run.by_step.values()] == ["fake"]


DIGEST = ("## what changed" + chr(10) + "- a.md | changed | x" + chr(10)
          + chr(10) + "## needs me" + chr(10) + "- b.md | needs-me | y" + chr(10))


def scored(monkeypatch, reply=None):
    """a real case through the real flow, scored the way the harness scores it."""
    from agentweft.runner import engine

    monkeypatch.setattr(engine, "CACHE", {})
    case = harness.load_case(harness.cases_for("weekly-digest")[0])
    if reply is not None:
        case["provider"] = {"provider": "fake", "reply": reply}
    return harness.score(runner.config("weekly-digest"),
                         *harness.run_flow_for("weekly-digest", case))


def test_a_case_runs_every_step_of_its_flow(monkeypatch):
    r = scored(monkeypatch, DIGEST)
    assert r["calls"] == 5
    assert r["passed"] == r["checked"]


def test_a_gate_on_the_last_step_is_in_the_score(monkeypatch):
    r = scored(monkeypatch, DIGEST + chr(10) + "here is the digest" + chr(10))
    assert r["calls"] == 5
    assert r["passed"] < r["checked"]
    assert [row["detail"] for row in r["rows"] if row["ok"] is False] == [
        "gate regex failed at reviewer.md"]


def test_a_run_that_stops_early_is_not_scored_on_the_empty_text(monkeypatch):
    """the fake's own answer has no tasks in it, so the fanned out step makes
    nothing, and nothing breaks any promise."""
    r = scored(monkeypatch)
    assert r["passed"] < r["checked"]
    assert [row["detail"] for row in r["rows"] if row["ok"] is False] == [
        "nothing came out of worker.md"]


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
