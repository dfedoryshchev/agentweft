"""what a run is charged, when the provider says and when it does not.

a provider that reports usage is charged exactly that, split the way it
reports it. one that reports nothing is charged the chars/4 estimate. the two
are never added into one number without the summary saying so.
"""
import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails.budget import Budget
from agentweft.providers.base import Reply, Usage
from agentweft.roles import resolver
from agentweft.runner import engine, prompts, state

CLAUDE = "provider:\n  provider: cli\n  command: claude\n  model: m-small\n"
FAKE = "provider:\n  provider: fake\n"

HEAVY = {"input_tokens": 10, "output_tokens": 40,
         "cache_read_input_tokens": 12000,
         "cache_creation_input_tokens": 800,
         "output_tokens_details": {"thinking_tokens": 25}}


def counted(raw, text="done"):
    return Reply(text, usage=Usage.of(raw))


def answer(text, usage=None):
    """what `claude -p --output-format json` prints for one call."""
    said = {"type": "result", "is_error": False, "result": text,
            "session_id": "s-1", "total_cost_usd": 0.25,
            "modelUsage": {"m-small-1": {}}}
    if usage is not None:
        said["usage"] = usage
    return (0, json.dumps(said).encode("utf-8"), b"")


def a_flow(tmp_path, monkeypatch, name, steps, tail=CLAUDE, args=()):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + "\nsteps:\n"
    for s in steps:
        role = s.split("\n")[0]
        body = body + "  - role: " + role + "\n    prompt: " + role + ".md\n"
        for more in s.split("\n")[1:]:
            body = body + "    " + more + "\n"
        (d / (role + ".md")).write_text("# " + role + "\n\ndo it.\n",
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body + tail, encoding="utf-8")
    (d / "instructions.md").write_text("the " + name + " flow.\n",
                                       encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force"] + list(args))


def no_waiting(monkeypatch):
    real = engine.retry
    monkeypatch.setattr(engine, "retry",
                        lambda fn, cap=3: real(fn, cap, sleep=lambda s: None))


def run_for(name):
    spec = engine.config(name)
    by_role = resolver.resolve(spec.raw, prompts.flow_path(name))
    return engine.Run(name, spec, by_role)


def journal():
    return (state.RUNS / "journal.md").read_text(encoding="utf-8")


# the budget on its own


def test_a_reply_with_usage_is_charged_exactly_that():
    b = Budget()
    b.charge("a prompt nobody measures", counted({"input_tokens": 7,
                                                  "output_tokens": 3}))
    assert b.counted == {"input": 7, "output": 3, "cache_read": 0,
                         "cache_creation": 0, "reasoning": 0}
    assert (b.calls, b.tokens, b.estimated, b.metered()) == \
        (1, 10, 0, "counted")


def test_cache_and_reasoning_are_parts_of_the_totals_never_added_again():
    b = Budget()
    b.charge("p", counted(HEAVY))
    assert b.counted == {"input": 12810, "output": 40, "cache_read": 12000,
                         "cache_creation": 800, "reasoning": 25}
    assert b.tokens == 12850
    assert b.summary() == ("1 call, 12850 tokens counted (input 12810 incl."
                           " cache_read 12000 and cache_creation 800, output 40"
                           " incl. reasoning 25), unpriced: no model named x1"
                           " (cli x1)")


def test_a_reply_with_nothing_reported_is_estimated_at_chars_over_four():
    b = Budget()
    b.charge("x" * 40, Reply("y" * 20))
    assert (b.tokens, b.estimated, b.estimated_calls) == (15, 15, 1)
    assert b.counted == dict.fromkeys(b.counted, 0)
    assert b.metered() == "estimated"
    assert b.summary() == ("1 call, ~15 tokens estimated, unpriced: no model"
                           " named x1 (cli x1)")


def test_the_old_text_only_charge_is_still_an_estimate():
    b = Budget()
    b.charge("x" * 40, "y" * 20, provider="fake")
    assert (b.tokens, b.metered()) == (15, "estimated")
    assert b.summary() == ("1 call, ~15 tokens estimated, unpriced: no model"
                           " named x1 (fake x1)")


def test_a_usage_block_with_fields_missing_is_counted_as_far_as_it_goes():
    b = Budget()
    b.charge("x" * 4000, counted({"output_tokens": 5}))
    b.charge("x" * 4000, counted({}))
    assert b.counted == {"input": 0, "output": 5, "cache_read": 0,
                         "cache_creation": 0, "reasoning": 0}
    # a block that was sent is a count, even an empty one: no estimate
    assert (b.tokens, b.estimated_calls, b.metered()) == (5, 0, "counted")


def test_a_usage_block_of_the_wrong_type_counts_as_zero_not_a_crash():
    b = Budget()
    b.charge("p", counted({"input_tokens": "12", "output_tokens": None,
                           "output_tokens_details": {"thinking_tokens": "3"}}))
    assert b.tokens == 0 and b.counted["reasoning"] == 0
    assert b.metered() == "counted"


def test_a_mixed_run_says_how_many_calls_were_estimated():
    b = Budget()
    b.charge("p", counted({"input_tokens": 100, "output_tokens": 20}))
    b.charge("x" * 40, Reply("y" * 20), provider="fake")
    b.charge("x" * 40, Reply("y" * 20), provider="fake")
    assert b.metered() == "mixed: 2 estimated calls"
    assert b.summary() == ("3 calls, mixed: 2 estimated calls, 120 tokens"
                           " counted (input 100, output 20) + ~30 estimated,"
                           " unpriced: no model named x3 (cli x1, fake x2)")


def test_one_estimated_call_is_singular():
    b = Budget()
    b.charge("p", counted({"input_tokens": 1, "output_tokens": 1}))
    b.charge("x" * 4, Reply("y" * 4))
    assert b.metered() == "mixed: 1 estimated call"


def test_a_failed_go_with_nothing_reported_is_charged_zero_with_its_kind():
    b = Budget()
    b.charge("x" * 4000, Reply("", detail="timed out"), error="transient")
    assert (b.calls, b.tokens, b.estimated_calls) == (1, 0, 0)
    assert b.unreported == {"transient": 1}
    assert b.summary() == ("1 call, 0 tokens, 1 failed call charged 0"
                           " (transient x1) (cli x1)")


def test_a_failed_go_the_provider_counted_is_charged_what_it_counted():
    b = Budget()
    b.charge("p", Reply("", detail="an empty answer",
                        usage=Usage.of({"input_tokens": 9, "output_tokens": 0})),
             error="transient")
    assert (b.tokens, b.unreported, b.metered()) == (9, {}, "counted")


def test_the_token_cap_trips_on_counted_tokens_only_past_the_cap():
    b = Budget(max_tokens=850)
    b.charge("p", counted(HEAVY))
    assert b.over() is None
    b.charge("p", counted({"output_tokens": 1}))
    assert b.over() == ("token cap: 851 > 850 (851 counted: input 10,"
                        " cache_creation 800, output 41; cache_read 12000"
                        " not counted)")


def test_a_set_token_cap_leaves_cache_reads_out():
    """a cache read is the same prompt read again at a tenth of the price. a
    cap counting it trips on runs that cost next to nothing."""
    b = Budget(max_tokens=1000)
    b.charge("p", counted({"input_tokens": 100, "output_tokens": 50,
                           "cache_read_input_tokens": 300000,
                           "cache_creation_input_tokens": 200}))
    assert b.over() is None
    assert b.tokens == 300350


def test_the_token_cap_names_both_halves_of_a_mixed_total():
    b = Budget(max_tokens=100)
    b.charge("p", counted({"input_tokens": 90, "output_tokens": 0}))
    b.charge("x" * 40, Reply("y" * 20))
    assert b.over() == ("token cap: 105 > 100 (90 counted: input 90,"
                        " output 0, + ~15 estimated)")


def test_the_token_cap_on_an_estimate_alone_says_it_is_an_estimate():
    b = Budget(max_tokens=1)
    b.charge("x" * 100, "y" * 100)
    assert b.over() == "token cap: 50 > 1 (~50 estimated)"


def test_the_call_cap_counts_failed_goes_and_trips_only_past_the_cap():
    b = Budget(max_calls=2)
    b.charge("p", Reply("", detail="timed out"), error="transient")
    b.charge("p", counted({"input_tokens": 1, "output_tokens": 1}))
    assert b.over() is None
    b.charge("p", counted({"input_tokens": 1, "output_tokens": 1}))
    assert b.over() == "call cap: 3 > 2"


def refusal():
    return Reply("", detail="limit reached", outage="unknown",
                 usage=Usage.of({"input_tokens": 0, "output_tokens": 0}))


def test_a_refusal_counted_at_zero_tokens_is_not_a_call():
    b = Budget(max_calls=2)
    b.charge("p", counted({"input_tokens": 1, "output_tokens": 1}))
    for _ in range(9):
        b.charge("p", refusal(), error="outage")
    assert b.over() is None
    assert (b.calls, b.counted_calls) == (1, 1)
    assert b.refused_calls == 9


def test_nine_refusals_alone_read_as_refused_with_no_tokens():
    b = Budget()
    for _ in range(9):
        b.charge("p", refusal(), error="outage")
    assert b.summary() == "0 calls, 9 refused, 0 tokens"


def test_refusals_are_named_beside_the_work_calls():
    b = Budget()
    b.charge("p", counted({"input_tokens": 3, "output_tokens": 1}))
    b.charge("p", refusal(), error="outage")
    assert b.summary().startswith("1 call, 1 refused, 4 tokens counted")


def test_a_resumed_run_carries_its_refusals():
    b = Budget()
    b.charge("p", refusal(), error="outage")
    again = Budget().restore(b.saved())
    assert again.summary() == "0 calls, 1 refused, 0 tokens"


def test_a_failed_go_with_no_usage_block_is_still_a_call():
    b = Budget(max_calls=1)
    b.charge("p", Reply("", detail="timed out"), error="transient")
    b.charge("p", Reply("", detail="timed out"), error="transient")
    assert b.over() == "call cap: 2 > 1"


def test_nothing_charged_reads_as_nothing():
    assert Budget().summary() == "0 calls, 0 tokens"


# through the engine


def test_a_step_on_a_provider_that_counts_is_charged_its_count(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "metered", ["worker"])
    fake_cli(answer("done\n", usage=HEAVY))
    out, budget, stopped = engine.run_once("metered")
    assert stopped == ""
    assert budget.counted == {"input": 12810, "output": 40,
                              "cache_read": 12000, "cache_creation": 800,
                              "reasoning": 25}
    assert (budget.calls, budget.metered()) == (1, "counted")


def test_a_step_on_a_provider_that_says_nothing_is_estimated(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "quiet", ["worker"], tail=FAKE)
    sent = []
    real = engine.call
    monkeypatch.setattr(engine, "call", lambda prompt, **kw:
                        sent.append(prompt) or real(prompt, **kw))
    out, budget, stopped = engine.run_once("quiet")
    [prompt] = sent
    assert budget.tokens == (len(prompt) + len(out)) // 4
    assert (budget.calls, budget.metered()) == (1, "estimated")
    assert "~" + str(budget.tokens) + " tokens estimated" in budget.summary()


def test_a_step_that_fails_twice_then_answers_is_charged_three_goes(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "flaky", ["worker"])
    no_waiting(monkeypatch)
    fake_cli((1, b"", b"overloaded"), (1, b"", b"overloaded"),
             answer("done\n", usage={"input_tokens": 50, "output_tokens": 5}))
    out, budget, stopped = engine.run_once("flaky")
    assert out == "done\n"
    assert budget.calls == 3
    assert budget.unreported == {"transient": 2}
    assert budget.tokens == 55 and budget.metered() == "counted"


def test_every_counted_go_of_a_retried_step_is_in_the_total(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "empty-twice", ["worker"])
    no_waiting(monkeypatch)
    usage = {"input_tokens": 30, "output_tokens": 0}
    fake_cli(answer("", usage=usage), answer("", usage=usage),
             answer("done\n", usage={"input_tokens": 30, "output_tokens": 2}))
    out, budget, stopped = engine.run_once("empty-twice")
    assert (budget.calls, budget.tokens, budget.unreported) == (3, 92, {})


def test_a_step_that_never_answers_is_charged_every_go(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "down", ["worker"])
    no_waiting(monkeypatch)
    fake_cli((1, b"", b"overloaded"))
    out, budget, stopped = engine.run_once("down")
    assert stopped == "nothing came out of worker.md"
    assert (budget.calls, budget.tokens) == (3, 0)
    assert budget.unreported == {"transient": 3}


def test_a_run_over_two_kinds_of_provider_says_mixed_in_the_journal(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "both",
           ["worker", "reviewer\nprovider:\n  provider: fake\n"])
    fake_cli(answer("did it\n", usage={"input_tokens": 100,
                                       "output_tokens": 20}))
    engine.main()
    running, line = journal().strip().split("\n")
    assert "  running  " in running
    spend, pointer = line.rsplit("  ", 1)
    assert spend.endswith(" (cli x1, fake x1)")
    assert pointer.endswith("/handoff.md")
    assert "2 calls, mixed: 1 estimated call, 120 tokens counted" \
           " (input 100, output 20) + ~" in line


def test_a_cached_answer_is_not_charged(tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "again", ["worker"])
    fake_cli(answer("done\n", usage={"input_tokens": 5, "output_tokens": 1}))
    run = run_for("again")
    run.step("worker.md")
    run.step("worker.md")
    assert (run.budget.calls, run.budget.tokens) == (1, 6)


def test_a_bare_pair_from_a_stand_in_call_is_one_estimated_call(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "bare", ["worker"], tail=FAKE)
    monkeypatch.setattr(engine, "call", lambda *a, **k: ("x" * 400, False))
    run = run_for("bare")
    run.step("worker.md")
    assert (run.budget.calls, run.budget.metered()) == (1, "estimated")
    assert run.budget.tokens >= 100


def test_cache_writes_count_against_the_token_cap(tmp_path, monkeypatch,
                                                  fake_cli):
    """the prompt is a few dozen characters, so the estimate would never get
    near the cap; what the provider wrote to its cache does."""
    a_flow(tmp_path, monkeypatch, "cached-heavy", ["worker", "reviewer"],
           tail=CLAUDE + "max_tokens: 500\n")
    fake_cli(answer("did it\n", usage=HEAVY))
    engine.main()
    assert ("token cap: 850 of 500 spent, 170% (850 counted: input 10,"
            " cache_creation 800, output 40; cache_read 12000 not counted)") \
        in journal()


def test_an_ordinary_run_is_not_stopped_by_a_token_cap_it_never_set(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "ordinary", ["worker", "reviewer"])
    fake_cli(answer("VERDICT: ok\n\ndid it\n",
                    usage={"input_tokens": 100, "output_tokens": 500,
                           "cache_read_input_tokens": 300000,
                           "cache_creation_input_tokens": 20000}))
    assert engine.main() == 0
    assert "  budget  " not in journal()
    assert "  ordinary  ok  " in journal()


def test_the_cap_is_exact_at_the_boundary_through_the_engine(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "edge", ["worker", "reviewer"],
           tail=CLAUDE + "max_tokens: 850\n")
    cli = fake_cli(answer("did it\n", usage=HEAVY),
                   answer("VERDICT: ok\n\nfine\n", usage={"output_tokens": 1}))
    engine.main()
    assert ("reached, completion 1/2 steps, token cap: 850 of 850 spent, 100%"
            in journal())
    assert "  parked at reviewer.md  " in journal()
    assert "  budget  " in journal()
    assert len(cli.calls) == 1


def test_a_budget_stop_exits_like_any_other_stop(tmp_path, monkeypatch,
                                                 fake_cli):
    a_flow(tmp_path, monkeypatch, "pricey", ["worker", "reviewer"],
           tail=CLAUDE + "max_tokens: 5000\n")
    fake_cli(answer("did it\n", usage={"input_tokens": 6000,
                                       "output_tokens": 1}))
    assert engine.main() == 2
    assert "  budget  " in journal()


def test_the_eval_table_drops_the_tilde_only_for_a_counted_total():
    from agentweft.evals import harness

    spec = engine.config("weekly-digest")
    exact = Budget().charge("p", counted({"input_tokens": 9,
                                          "output_tokens": 1}))
    rough = Budget().charge("x" * 40, "")
    rows = [("exact", harness.score(spec, "", exact)),
            ("rough", harness.score(spec, "", rough))]
    text = harness.table("weekly-digest", rows)
    assert "1 calls, 10 tokens counted" in text
    assert "1 calls, ~10 tokens estimated" in text


@pytest.mark.parametrize("raw,want", [
    ({"input_tokens": 3, "output_tokens": 4}, 7),
    ({"input_tokens": 3, "cache_read_input_tokens": 4}, 7),
    ({"cache_creation_input_tokens": 6, "output_tokens": 1}, 7),
])
def test_the_total_is_input_plus_output_whatever_the_input_is_made_of(raw,
                                                                       want):
    b = Budget()
    b.charge("p", counted(raw))
    assert b.tokens == want
