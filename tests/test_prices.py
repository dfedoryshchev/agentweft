"""what a run cost in money: tokens through a price table.

the table is data a person edits. a model it does not list has no price, which
is not the same as free; the provider's own figure is kept beside the priced
one, and when the two disagree the line says by how much.
"""
import json
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import prices
from agentweft.guardrails.budget import Budget
from agentweft.providers.base import Reply, Usage
from agentweft.runner import engine, prompts, state, trace

TABLE = """\
source: https://example.invalid/prices
checked: 2026-10-12
web_search_per_1000: 10
models:
  m-big:
    ids: [m-big-20250101]
    input: 5
    cache_write_5m: 6.25
    cache_write_1h: 10
    cache_read: 0.50
    output: 25
  m-small:
    input: 1
    cache_write_5m: 1.25
    cache_write_1h: 2
    cache_read: 0.10
    output: 5
  m-tiered:
    input: 0.10
    cache_write_5m: 0.125
    cache_write_1h: 0.20
    cache_read: 0.01
    output: 0.50
    over: 100000
    above:
      input: 0.50
      cache_write_5m: 0.625
      cache_write_1h: 1
      cache_read: 0.05
      output: 2.50
"""


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "prices.yaml"
    path.write_text(TABLE, encoding="utf-8")
    return prices.load(path)


def usage(**raw):
    return Usage.of(raw)


def reply(model, cost=None, text="done", models=None, **raw):
    r = Reply(text, usage=Usage.of(raw), cost=cost, model=model)
    if models is not None:
        r.models = models
    return r


# the table


def test_the_shipped_table_says_where_its_numbers_came_from_and_when():
    t = prices.load(prices.SHIPPED)
    assert t.source == "https://platform.claude.com/docs/en/about-claude/pricing"
    assert t.checked == "2026-10-12"
    head = "\n".join(prices.SHIPPED.read_text(encoding="utf-8")
                     .split("\n")[:5])
    assert t.source in head and t.checked in head


def test_the_shipped_table_matches_what_the_cli_charged_on_a_real_call():
    """two `claude -p` answers kept from real runs, with every cache write on
    the one-hour lifetime: the table has to land on the cli's own figure to
    the last digit it printed."""
    t = prices.load(prices.SHIPPED)
    sonnet = usage(input_tokens=74, output_tokens=32568,
                   cache_read_input_tokens=2013575,
                   cache_creation_input_tokens=65747,
                   cache_creation={"ephemeral_1h_input_tokens": 65747,
                                   "ephemeral_5m_input_tokens": 0})
    assert t.price("claude-sonnet-5", sonnet).usd == Decimal("0.991531")
    opus = usage(input_tokens=6, output_tokens=626,
                 cache_read_input_tokens=53936,
                 cache_creation_input_tokens=9794,
                 cache_creation={"ephemeral_1h_input_tokens": 9794,
                                 "ephemeral_5m_input_tokens": 0})
    assert t.price("claude-opus-5-5", opus).usd == Decimal("0.1016832")


def test_a_model_under_another_of_its_names_is_the_same_price(table):
    u = usage(input_tokens=1000000)
    assert table.price("m-big-20250101", u).usd == Decimal(5)
    assert table.price("m-big", u).usd == Decimal(5)


@pytest.mark.parametrize("model", ["m-unknown", "m-big-2", "M-BIG", "", None])
def test_a_model_the_table_does_not_list_has_no_price_never_zero(table, model):
    p = table.price(model, usage(input_tokens=1000, output_tokens=10))
    assert p.usd is None
    assert p.missing == [prices.label(model)]


def test_a_table_with_a_rate_missing_is_refused_by_name(tmp_path):
    path = tmp_path / "prices.yaml"
    path.write_text("models:\n  m-x:\n    input: 1\n    output: 2\n",
                    encoding="utf-8")
    with pytest.raises(ValueError) as e:
        prices.load(path)
    assert "m-x" in str(e.value) and "cache_read" in str(e.value)


def test_a_negative_or_wordy_rate_is_refused(tmp_path):
    path = tmp_path / "prices.yaml"
    for bad in ("-1", "cheap"):
        path.write_text("models:\n  m-x:\n    input: " + bad + "\n"
                        "    cache_write_5m: 1\n    cache_write_1h: 1\n"
                        "    cache_read: 1\n    output: 1\n", encoding="utf-8")
        with pytest.raises(ValueError):
            prices.load(path)


def test_a_table_of_your_own_is_read_over_the_shipped_one(tmp_path,
                                                          monkeypatch):
    monkeypatch.delenv("PRICES", raising=False)
    monkeypatch.chdir(tmp_path)
    assert prices.load().source == prices.load(prices.SHIPPED).source
    (tmp_path / "prices.yaml").write_text(TABLE, encoding="utf-8")
    assert prices.load().source == "https://example.invalid/prices"
    other = tmp_path / "elsewhere.yaml"
    other.write_text(TABLE.replace("example.invalid", "other.invalid"),
                     encoding="utf-8")
    monkeypatch.setenv("PRICES", str(other))
    assert prices.load().source == "https://other.invalid/prices"


def test_an_edit_to_the_table_is_read_without_a_restart(tmp_path):
    path = tmp_path / "prices.yaml"
    path.write_text(TABLE, encoding="utf-8")
    assert prices.load(path).rates("m-small").input == Decimal(1)
    path.write_text(TABLE.replace("    input: 1\n", "    input: 2\n"),
                    encoding="utf-8")
    import os
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10 ** 9))
    assert prices.load(path).rates("m-small").input == Decimal(2)


# what a call costs


def test_cache_read_and_both_cache_writes_are_priced_at_their_own_rates(table):
    u = usage(input_tokens=1000000, output_tokens=1000000,
              cache_read_input_tokens=1000000,
              cache_creation_input_tokens=3000000,
              cache_creation={"ephemeral_5m_input_tokens": 1000000,
                              "ephemeral_1h_input_tokens": 2000000})
    # 5 + 25 + 0.50 + 6.25 + 2 x 10
    assert table.price("m-big", u).usd == Decimal("56.75")


def test_a_cache_write_with_no_lifetime_split_is_not_guessed(table):
    u = usage(input_tokens=10, output_tokens=1, cache_creation_input_tokens=500)
    p = table.price("m-big", u)
    assert p.usd is None
    assert p.missing == ["m-big (cache writes with no 5m / 1h split)"]


def test_a_split_that_does_not_add_up_is_not_trusted(table):
    u = usage(input_tokens=10, cache_creation_input_tokens=500,
              cache_creation={"ephemeral_5m_input_tokens": 100,
                              "ephemeral_1h_input_tokens": 100})
    assert table.price("m-big", u).usd is None


def test_no_cache_write_needs_no_split(table):
    u = usage(input_tokens=10, output_tokens=2, cache_read_input_tokens=1000)
    # 10 x 5 + 1000 x 0.50 + 2 x 25, per million
    assert table.price("m-big", u).usd == Decimal("0.0006")


def test_reasoning_is_output_and_is_not_charged_twice(table):
    u = usage(output_tokens=1000, output_tokens_details={"thinking_tokens": 900})
    assert table.price("m-small", u).usd == Decimal("0.005")


@pytest.mark.parametrize("raw,why", [
    ({"speed": "fast"}, "fast mode"),
    ({"inference_geo": "us"}, "US-only inference"),
])
def test_a_premium_the_table_has_no_rate_for_is_not_priced(table, raw, why):
    u = usage(input_tokens=10, output_tokens=1, **raw)
    p = table.price("m-big", u)
    assert p.usd is None and p.missing == ["m-big (" + why + ")"]


def test_standard_speed_and_global_inference_are_the_list_price(table):
    u = usage(input_tokens=1000000, speed="standard",
              inference_geo="not_available")
    assert table.price("m-big", u).usd == Decimal(5)


def test_web_searches_are_priced_per_search(table):
    u = usage(input_tokens=0, server_tool_use={"web_search_requests": 3})
    assert table.price("m-small", u).usd == Decimal("0.03")


def test_a_long_prompt_on_a_tiered_model_pays_the_upper_rate(table):
    u = Usage.of({"input_tokens": 150000, "output_tokens": 1000}, requests=1)
    # 0.15 x 0.50 + 0.001 x 2.50
    assert table.price("m-tiered", u, one_request=True).usd == Decimal("0.0775")


def test_a_tiered_model_at_the_threshold_is_still_the_lower_rate(table):
    u = usage(input_tokens=100000)
    assert table.price("m-tiered", u).usd == Decimal("0.01")


def test_a_sum_of_requests_past_the_threshold_is_not_guessed(table):
    """the cli reports one usage block for every request a session made, and
    the threshold is per request: a total past it does not say which ones
    crossed."""
    u = usage(input_tokens=150000)
    p = table.price("m-tiered", u)
    assert p.usd is None
    assert p.missing == ["m-tiered (over 100000 input tokens, summed over"
                         " requests)"]


def test_an_answer_from_two_models_is_priced_per_model(table):
    r = reply("m-big, m-small", input_tokens=2000000, output_tokens=0,
              models={"m-big": usage(input_tokens=1000000),
                      "m-small": usage(input_tokens=1000000)})
    assert prices.of_reply(table, r).usd == Decimal(6)


def test_an_answer_from_two_models_one_unpriced_has_no_total(table):
    r = reply("m-big, m-other", input_tokens=2,
              models={"m-big": usage(input_tokens=1),
                      "m-other": usage(input_tokens=1)})
    p = prices.of_reply(table, r)
    assert p.usd is None and p.missing == ["m-other"]


def test_two_model_names_with_no_split_are_not_priced_as_either(table):
    r = reply("m-big, m-small", input_tokens=2)
    p = prices.of_reply(table, r)
    assert p.usd is None
    assert p.missing == ["m-big, m-small (several models, no split)"]


def test_the_model_that_answered_wins_over_the_one_asked_for(table):
    r = reply("m-small", input_tokens=1000000)
    assert prices.of_reply(table, r, asked="m-big").usd == Decimal(1)
    r = reply(None, input_tokens=1000000)
    assert prices.of_reply(table, r, asked="m-big").usd == Decimal(5)


@pytest.mark.parametrize("usd,shown", [
    (Decimal("0.12345"), "$0.1235"),
    (Decimal("0.12344"), "$0.1234"),
    (Decimal("0.00005"), "$0.0001"),
    (Decimal("0.00004"), "<$0.0001"),
    (Decimal("0"), "$0.0000"),
    (Decimal("12"), "$12.0000"),
])
def test_money_is_shown_to_a_hundredth_of_a_cent(usd, shown):
    assert prices.money(usd) == shown


def test_a_counted_run_is_priced_and_the_provider_figure_kept_beside_it(table):
    b = Budget(prices=table)
    b.charge("p", reply("m-small", cost=0.005, input_tokens=1000,
                        output_tokens=800))
    m = b.money()
    assert m["usd"] == 0.005 and m["estimated"] is False
    assert m["reported_usd"] == 0.005 and m["unpriced"] == {}
    assert b.summary() == ("1 call, 1800 tokens counted (input 1000,"
                           " output 800), $0.0050 priced, reported $0.0050"
                           " (cli x1)")


def test_a_priced_total_the_provider_disagrees_with_says_by_how_much(table):
    b = Budget(prices=table)
    b.charge("p", reply("m-small", cost=0.0066, input_tokens=1000,
                        output_tokens=800))
    assert b.money()["usd"] == 0.005
    assert b.money()["reported_usd"] == 0.0066
    assert b.summary().endswith(", $0.0050 priced, reported $0.0066, they"
                                " differ by $0.0016 (cli x1)")


def test_a_difference_below_what_is_shown_is_not_a_disagreement(table):
    b = Budget(prices=table)
    b.charge("p", reply("m-small", cost=0.00500004, input_tokens=1000,
                        output_tokens=800))
    assert "differ" not in b.summary()


def test_an_unpriced_model_reports_tokens_and_no_money(table):
    b = Budget(prices=table)
    b.charge("p", reply("m-other", cost=0.25, input_tokens=100,
                        output_tokens=20))
    m = b.money()
    assert m["usd"] is None and m["unpriced"] == {"m-other": 1}
    assert b.summary() == ("1 call, 120 tokens counted (input 100, output 20),"
                           " unpriced: m-other x1, reported $0.2500 (cli x1)")


def test_a_run_over_two_models_one_unpriced_shows_the_part_it_could_price(
        table):
    b = Budget(prices=table)
    b.charge("p", reply("m-small", input_tokens=1000000))
    b.charge("p", reply("m-other", input_tokens=10))
    b.charge("p", reply("m-other", input_tokens=10))
    m = b.money()
    assert m["usd"] is None and m["priced_usd"] == 1.0
    assert m["unpriced"] == {"m-other": 2}
    assert ", $1.0000 priced + unpriced: m-other x2 (cli x3)" in b.summary()


def test_a_run_over_two_priced_models_adds_them(table):
    b = Budget(prices=table)
    b.charge("p", reply("m-small", input_tokens=1000000))
    b.charge("p", reply("m-big", input_tokens=1000000))
    assert b.money()["usd"] == 6.0


def test_a_cache_heavy_run_is_priced_at_the_cache_rates(table):
    b = Budget(prices=table)
    b.charge("p", reply("m-big", input_tokens=10, output_tokens=40,
                        cache_read_input_tokens=12000,
                        cache_creation_input_tokens=800,
                        cache_creation={"ephemeral_5m_input_tokens": 0,
                                        "ephemeral_1h_input_tokens": 800}))
    # 10 x 5 + 12000 x 0.50 + 800 x 10 + 40 x 25, per million
    assert b.money()["usd"] == 0.01505


def test_an_estimated_run_is_priced_as_an_estimate(table):
    b = Budget(prices=table)
    b.charge("x" * 4000000, Reply("y" * 400000), model="m-small")
    m = b.money()
    assert m["estimated"] is True and m["usd"] == 1.5
    assert b.summary() == ("1 call, ~1100000 tokens estimated, ~$1.5000"
                           " priced (cli x1)")


def test_a_run_part_counted_part_estimated_says_how_much_is_the_estimate(
        table):
    b = Budget(prices=table)
    b.charge("p", reply("m-small", input_tokens=1000000))
    b.charge("x" * 400000, Reply("y" * 40000), model="m-small")
    assert b.money()["usd"] == 1.15
    assert ", ~$1.1500 priced (~$0.1500 of it estimated) (cli x2)" \
        in b.summary()


def test_an_estimate_with_no_model_has_no_price(table):
    b = Budget(prices=table)
    b.charge("x" * 40, Reply("y" * 20), provider="fake")
    assert b.money()["unpriced"] == {"no model named": 1}
    assert b.summary() == ("1 call, ~15 tokens estimated, unpriced: no model"
                           " named x1 (fake x1)")


def test_a_provider_figure_on_some_calls_only_says_on_how_many(table):
    b = Budget(prices=table)
    b.charge("p", reply("m-small", cost=0.001, input_tokens=1000))
    b.charge("p", reply("m-small", input_tokens=1000))
    assert b.money()["reported_usd"] is None
    assert ", reported $0.0010 on 1 of 2 calls (cli x2)" in b.summary()


def test_failed_goes_alone_have_no_money_part(table):
    b = Budget(prices=table)
    b.charge("p", Reply("", detail="timed out"), error="transient")
    assert b.money()["usd"] == 0
    assert b.summary() == ("1 call, 0 tokens, 1 failed call charged 0"
                           " (transient x1) (cli x1)")


def test_nothing_charged_costs_nothing(table):
    assert Budget(prices=table).money()["usd"] == 0
    assert Budget(prices=table).summary() == "0 calls, 0 tokens"


def test_the_money_record_names_the_table_it_was_priced_by(table):
    assert Budget(prices=table).money()["prices"] == \
        "https://example.invalid/prices, checked 2026-10-12"


# through the engine


CLAUDE = "provider:\n  provider: cli\n  command: claude\n  model: {model}\n"


def a_flow(tmp_path, monkeypatch, name, steps, model):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + "\nsteps:\n"
    for role in steps:
        body = body + "  - role: " + role + "\n    prompt: " + role + ".md\n"
        (d / (role + ".md")).write_text("# " + role + "\n\ndo it.\n",
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body + CLAUDE.format(model=model),
                                 encoding="utf-8")
    (d / "instructions.md").write_text("the " + name + " flow.\n",
                                       encoding="utf-8")
    (tmp_path / "prices.yaml").write_text(TABLE, encoding="utf-8")
    monkeypatch.delenv("PRICES", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force"])


def answer(text, model, cost, **raw):
    said = {"type": "result", "is_error": False, "result": text,
            "session_id": "s-1", "total_cost_usd": cost, "usage": raw,
            "modelUsage": {model: {}}}
    return (0, json.dumps(said).encode("utf-8"), b"")


def test_the_journal_line_and_every_step_line_carry_the_money(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "priced", ["worker", "reviewer"], "m-small")
    fake_cli(answer("did it\n", "m-small", 0.005, input_tokens=1000,
                    output_tokens=800),
             answer("VERDICT: ok\n\nfine\n", "m-small", 0.005,
                    input_tokens=1000, output_tokens=800))
    assert engine.main() == 0
    line = (state.RUNS / "journal.md").read_text(encoding="utf-8") \
        .strip().split("\n")[-1]
    line = line.rsplit("  ", 1)[0]
    assert line.endswith("3600 tokens counted (input 2000, output 1600),"
                         " $0.0100 priced, reported $0.0100 (cli x2)")
    [folder] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    steps = [json.loads(l) for l in (folder / trace.FILE)
             .read_text(encoding="utf-8").split("\n") if l]
    assert [s["priced"] for s in steps] == [0.005, 0.005]
    assert list(steps[0]).index("priced") == list(steps[0]).index("cost") + 1


def test_a_step_on_a_model_the_table_lacks_is_priced_null(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "unlisted", ["worker"], "m-new")
    fake_cli(answer("did it\n", "m-new", 0.25, input_tokens=100,
                    output_tokens=20))
    assert engine.main() == 0
    text = (state.RUNS / "journal.md").read_text(encoding="utf-8")
    assert ", unpriced: m-new x1, reported $0.2500 (cli x1)" in text
    [folder] = [p for p in state.RUNS.iterdir() if p.is_dir()]
    [step] = [json.loads(l) for l in (folder / trace.FILE)
              .read_text(encoding="utf-8").split("\n") if l]
    assert step["priced"] is None and step["cost"] == 0.25


def test_a_cli_answer_from_two_models_is_split_per_model(fake_cli, table):
    from agentweft import providers

    said = {"type": "result", "is_error": False, "result": "ok",
            "total_cost_usd": 6.0,
            "usage": {"input_tokens": 2000000, "output_tokens": 0,
                      "cache_creation_input_tokens": 2000000,
                      "cache_creation": {"ephemeral_1h_input_tokens": 2000000,
                                         "ephemeral_5m_input_tokens": 0}},
            "modelUsage": {
                "m-big": {"inputTokens": 1000000, "outputTokens": 0,
                          "cacheCreationInputTokens": 1000000},
                "m-small": {"inputTokens": 1000000, "outputTokens": 0,
                            "cacheCreationInputTokens": 1000000}}}
    fake_cli((0, json.dumps(said).encode("utf-8"), b""))
    r = providers.build({"provider": "cli", "command": "claude"}).ask("x")
    assert sorted(r.models) == ["m-big", "m-small"]
    # 5 + 10 (one-hour writes) on m-big, 1 + 2 on m-small
    assert prices.of_reply(table, r).usd == Decimal(18)


def test_a_cli_answer_from_two_models_over_both_lifetimes_is_not_guessed(
        fake_cli, table):
    from agentweft import providers

    said = {"type": "result", "is_error": False, "result": "ok",
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 20,
                      "cache_creation": {"ephemeral_1h_input_tokens": 10,
                                         "ephemeral_5m_input_tokens": 10}},
            "modelUsage": {"m-big": {"inputTokens": 1,
                                     "cacheCreationInputTokens": 10},
                           "m-small": {"inputTokens": 1,
                                       "cacheCreationInputTokens": 10}}}
    fake_cli((0, json.dumps(said).encode("utf-8"), b""))
    r = providers.build({"provider": "cli", "command": "claude"}).ask("x")
    p = prices.of_reply(table, r)
    assert p.usd is None and len(p.missing) == 2


def test_an_api_answer_is_one_request(monkeypatch):
    from agentweft.providers import api_provider

    class Fake(object):
        status_code = 200

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 3, "output_tokens": 1},
                    "model": "m-tiered"}

    monkeypatch.setattr(api_provider.httpx, "post", lambda *a, **k: Fake())
    monkeypatch.setenv("API_KEY", "k")
    p = api_provider.ApiProvider(model="m-tiered")
    assert p.ask("x").usage.requests == 1


# python run.py spend


def write_run(runs, run, flow, steps, spend="1 call"):
    folder = runs / run
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / trace.FILE, "a", encoding="utf-8") as f:
        for s in steps:
            f.write(json.dumps(s) + "\n")
    with open(runs / "journal.md", "a", encoding="utf-8") as f:
        f.write("2026-10-12 09:00  " + flow + "  ok  4s  " + run
                + "  out.md  " + spend + "\n")


def step(provider, priced=None, cost=None, counted=True, cached=False):
    tokens = {"counted": False}
    if counted:
        tokens = {"counted": True, "input": 100, "output": 10,
                  "cache_read": 40, "cache_creation": 20}
    return {"provider": provider, "tokens": tokens, "priced": priced,
            "cost": cost, "cached": cached}


def test_spend_groups_the_runs_per_flow_and_per_provider(tmp_path, monkeypatch,
                                                         capsys):
    from agentweft.runner import cli

    runs = tmp_path / "runs"
    monkeypatch.setattr(state, "RUNS", runs)
    write_run(runs, "digest-1", "digest",
              [step("cli", 0.01, 0.01), step("cli", 0.02, 0.02)])
    write_run(runs, "digest-2", "digest",
              [step("cli", None, 0.25), step("fake", counted=False)])
    write_run(runs, "audit-1", "audit", [step("fake", counted=False),
                                         step("fake", cached=True,
                                              counted=False)])
    assert cli.cmd_spend() == 0
    out = capsys.readouterr().out.split("\n")
    assert out[:3] == [l for l in (runs / "journal.md").read_text(
        encoding="utf-8").split("\n") if l]
    flows = out[out.index("per flow") + 1:out.index("per provider") - 1]
    assert flows == [
        "  audit  1 run, 1 step, estimated only: no counts, no money",
        "  digest  2 runs, 4 steps, input 300, output 30, cache read 120,"
        " cache write 60, $0.0300 priced + 1 unpriced step, 1 step estimated,"
        " not counted, reported $0.2800 on 3 of 4 steps"]
    providers = out[out.index("per provider") + 1:]
    assert providers[0] == ("  cli  2 runs, 3 steps, input 300, output 30,"
                            " cache read 120, cache write 60, $0.0300 priced"
                            " + 1 unpriced step, reported $0.2800")
    assert providers[1] == ("  fake  2 runs, 2 steps, estimated only: no"
                            " counts, no money")


def test_a_resumed_run_is_counted_once(tmp_path, monkeypatch, capsys):
    from agentweft.runner import cli

    runs = tmp_path / "runs"
    monkeypatch.setattr(state, "RUNS", runs)
    write_run(runs, "digest-1", "digest", [step("cli", 0.01, 0.01)])
    write_run(runs, "digest-1", "digest", [step("cli", 0.02, 0.02)])
    cli.cmd_spend()
    out = capsys.readouterr().out
    assert "  digest  1 run, 2 steps, " in out and "$0.0300 priced" in out


def test_the_eval_record_carries_the_money_for_cost_per_result(table):
    from agentweft.evals import harness

    spec = engine.config("weekly-digest")
    b = Budget(prices=table)
    b.charge("p", reply("m-small", cost=0.005, input_tokens=1000,
                        output_tokens=800))
    rough = Budget(prices=table)
    rough.charge("x" * 40, "")
    exact = harness.score(spec, "", b)
    assert (exact["usd"], exact["usd_estimated"], exact["reported_usd"]) == \
        (0.005, False, 0.005)
    assert harness.score(spec, "", rough)["usd"] is None
    text = harness.table("weekly-digest", [("exact", exact)])
    assert "$0.0050 priced" in text
