"""what a run keeps of the answers it got, and when a failed go is tried
again."""
import json
import sys

import httpx
import pytest

sys.path.insert(0, ".")
from agentweft.evals import harness
from agentweft.providers.base import Provider, Reply
from agentweft.roles import resolver
from agentweft.runner import engine, errors, prompts

CLAUDE = "provider:\n  provider: cli\n  command: claude\n  model: m-small\n"
FAKE = "provider:\n  provider: fake\n"


def answer(text):
    return (0, json.dumps({"type": "result", "is_error": False,
                           "result": text, "session_id": "s-1",
                           "usage": {"input_tokens": 5, "output_tokens": 1}})
            .encode("utf-8"), b"")


def a_flow(tmp_path, monkeypatch, name, steps, tail=FAKE):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + "\nsteps:\n"
    for role in steps:
        body = body + "  - role: " + role + "\n    prompt: " + role + ".md\n"
        (d / (role + ".md")).write_text("# " + role + "\n\ndo it.\n",
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body + tail, encoding="utf-8")
    (d / "instructions.md").write_text("the " + name + " flow.\n",
                                       encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force"])


def run_for(name):
    spec = engine.config(name)
    by_role = resolver.resolve(spec.raw, prompts.flow_path(name))
    return engine.Run(name, spec, by_role)


class Scripted(Provider):
    """hands back the replies it was given, in order, the last one for good."""

    name = "scripted"

    def __init__(self, *replies):
        Provider.__init__(self)
        self.replies = list(replies)
        self.asked = 0

    def ask(self, prompt, timeout=None):
        self.asked += 1
        return self.replies.pop(0) if len(self.replies) > 1 \
            else self.replies[0]


def slept_through(monkeypatch):
    slept = []
    real = engine.retry
    monkeypatch.setattr(engine, "retry",
                        lambda fn, cap=3: real(fn, cap, sleep=slept.append))
    return slept


# the cache


def test_two_runs_on_different_providers_each_get_their_own_answer(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "same", ["worker"])
    first, _, _ = engine.run_once("same", provider={"provider": "fake",
                                                    "reply": "from a\n"})
    second, budget, _ = engine.run_once("same", provider={"provider": "fake",
                                                          "reply": "from b\n"})
    assert (first, second) == ("from a\n", "from b\n")
    assert budget.calls == 1


def test_two_runs_on_the_same_provider_do_not_share_answers(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "twice", ["worker"], tail=CLAUDE)
    cli = fake_cli(answer("first\n"), answer("second\n"))
    first, _, _ = engine.run_once("twice")
    second, budget, _ = engine.run_once("twice")
    assert (first, second) == ("first\n", "second\n")
    assert len(cli.calls) == 2 and budget.calls == 1


def test_a_redo_inside_one_run_still_comes_from_the_cache(
        tmp_path, monkeypatch, fake_cli):
    a_flow(tmp_path, monkeypatch, "again", ["worker"], tail=CLAUDE)
    cli = fake_cli(answer("done\n"))
    run = run_for("again")
    run.step("worker.md")
    again = run.step("worker.md")
    assert again.meta["cached"] is True and len(cli.calls) == 1


def test_the_same_prompt_to_two_providers_in_one_run_is_asked_of_both(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "pair", ["worker"])
    run = run_for("pair")
    a, b = Scripted(Reply("from a")), Scripted(Reply("from b"))
    assert run.ask("p", "worker.md", a) == ("from a", False)
    assert run.ask("p", "worker.md", b) == ("from b", False)
    assert run.ask("p", "worker.md", a) == ("from a", True)
    assert (a.asked, b.asked) == (1, 1)


def test_an_answer_given_up_on_is_not_cached(tmp_path, monkeypatch,
                                            fake_cli):
    a_flow(tmp_path, monkeypatch, "flaky", ["worker"], tail=CLAUDE)
    slept_through(monkeypatch)
    run = run_for("flaky")
    cli = fake_cli(*([(1, b"", b"overloaded")] * run.retries
                     + [answer("done\n")]))
    assert not run.step("worker.md")
    later = run.step("worker.md")
    assert (later.output, later.meta["cached"]) == ("done\n", False)
    assert len(cli.calls) == run.retries + 1


def test_a_call_with_no_cache_keeps_nothing():
    p = Scripted(Reply("one"), Reply("two"))
    assert engine.call("p", provider=p) == ("one", False)
    assert engine.call("p", provider=p) == ("two", False)


def test_the_process_holds_no_answers_of_its_own():
    assert not hasattr(engine, "CACHE")


def test_two_eval_cases_on_one_flow_do_not_share_answers(monkeypatch):
    case = harness.load_case(harness.cases_for("weekly-digest")[0])
    seen = []
    for word in ("first", "second"):
        case["provider"] = {"provider": "fake", "reply": (
            "VERDICT: ok\n\n## what changed\n- a.md | changed | " + word
            + "\n\n## needs me\n- b.md | needs-me | y\n")}
        out, budget, _ = harness.run_flow_for("weekly-digest", case)
        seen.append((out, budget.calls))
    assert seen[0][0] != seen[1][0]
    assert seen[0][1] == seen[1][1]


# going again


def test_the_last_failed_go_is_not_followed_by_a_wait():
    slept = []
    assert engine.retry(lambda: (False, ""), cap=3, sleep=slept.append) == ""
    assert slept == [2, 4]


def test_a_go_that_answers_second_waits_once():
    slept = []
    goes = iter([(False, ""), (True, "yes")])
    assert engine.retry(lambda: next(goes), cap=3, sleep=slept.append) == "yes"
    assert slept == [2]


def test_a_cap_of_one_never_waits():
    slept = []
    engine.retry(lambda: (False, ""), cap=1, sleep=slept.append)
    assert slept == []


def test_a_reply_marked_not_retryable_is_asked_once(monkeypatch):
    slept = slept_through(monkeypatch)
    # the words would read as a timeout; the field says otherwise
    p = Scripted(Reply("", detail="timed out talking to it", retryable=False))
    with pytest.raises(errors.Fatal):
        engine.call("p", provider=p)
    assert p.asked == 1 and slept == []


def test_a_reply_marked_retryable_is_tried_again_whatever_it_says(
        monkeypatch):
    slept_through(monkeypatch)
    p = Scripted(Reply("", detail="401 unauthorized", retryable=True),
                 Reply("done"))
    assert engine.call("p", provider=p) == ("done", False)
    assert p.asked == 2


def test_the_field_is_read_before_the_words():
    assert errors.kind_of(Reply("", detail="timed out",
                                retryable=False)) is errors.Fatal
    assert errors.kind_of(Reply("", detail="not found",
                                retryable=True)) is errors.Transient
    assert errors.kind_of(Reply("", detail="not found")) is errors.Fatal
    assert errors.kind_of(Reply("", detail="limit", retryable=True,
                                outage="unknown")) is errors.Outage


def test_a_command_that_is_not_there_is_asked_once(tmp_path, monkeypatch,
                                                  fake_cli):
    a_flow(tmp_path, monkeypatch, "missing", ["worker"], tail=CLAUDE)
    slept = slept_through(monkeypatch)
    cli = fake_cli((FileNotFoundError(), b"", b""))
    run = run_for("missing")
    with pytest.raises(errors.Fatal, match="not on PATH"):
        run.step("worker.md")
    assert len(cli.calls) == 1 and slept == []


def test_a_go_that_failed_for_good_is_still_charged(tmp_path, monkeypatch,
                                                    fake_cli):
    a_flow(tmp_path, monkeypatch, "refused", ["worker"], tail=CLAUDE)
    slept_through(monkeypatch)
    fake_cli((1, b"", b"overloaded"), (1, b"", b"invalid api key"))
    run = run_for("refused")
    with pytest.raises(errors.Fatal):
        run.step("worker.md")
    assert run.budget.calls == 2
    assert run.budget.unreported == {"transient": 1, "fatal": 1}


def test_the_api_provider_with_no_key_is_not_retried(monkeypatch):
    from agentweft.providers.api_provider import ApiProvider

    monkeypatch.delenv("API_KEY", raising=False)
    assert ApiProvider().ask("p").retryable is False


@pytest.mark.parametrize("raised,again", [
    (httpx.UnsupportedProtocol("missing an 'http://' or 'https://'"), False),
    (httpx.RemoteProtocolError("server disconnected"), True),
    (httpx.ConnectError("connection refused"), True),
])
def test_an_api_call_that_never_got_an_answer_says_whether_to_go_again(
        monkeypatch, raised, again):
    from agentweft import providers

    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("MODEL", "m")

    def fails(*a, **kw):
        raise raised

    monkeypatch.setattr(httpx, "post", fails)
    p = providers.build({"provider": "api", "url": "example.invalid"})
    assert p.ask("x").retryable is again
