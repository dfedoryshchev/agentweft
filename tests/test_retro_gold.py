"""the retro held to a gold: four recorded runs, each with one failed attempt
whose cause is in the record, a fifth whose renamed flag left a README line
stale, a sixth whose lead ruled on a question with a clause still open, and
the answer a careful reader writes for each. the scorer checks
the attempt, the cause, the file to change, the fact and the doc edit by
program, and step mode asks the retro role alone on a record."""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.bench import __main__ as bench
from agentweft.bench import retrogold
from agentweft.providers import Provider, Reply, base
from agentweft.providers.base import Usage
from agentweft.runner import upkeep

CASES = Path(__file__).resolve().parent.parent / "bench" / "retro-gold"
NAMES = ["cross-file", "layered", "refactor", "renamed-flag", "ruled-open",
         "shift"]
FAILED = [n for n in NAMES if n not in ("renamed-flag", "ruled-open")]
STALE = CASES / "renamed-flag"
RULED = CASES / "ruled-open"
WANTED = {"renamed-flag": {"edit"}, "ruled-open": {"fact"}}


def test_the_six_cases_are_there_each_with_its_record_and_gold():
    assert [c.name for c in retrogold.cases(CASES)] == NAMES
    for case in retrogold.cases(CASES):
        gold = retrogold.gold_of(case)
        wanted = WANTED.get(case.name, {"failed", "cause", "change", "fact"})
        assert set(gold) >= wanted, case.name
        assert (case / "record" / "steps.jsonl").is_file(), case.name


def test_a_ruled_decision_with_an_open_clause_scores_only_as_important():
    gold = retrogold.gold_of(RULED)
    assert gold["fact"] == {"scope": ["logcount/filters.py"],
                            "kind": ["why", "decision"], "label": "important"}
    answer = retrogold.answer_of(RULED)
    assert "is open" in answer
    assert retrogold.score(answer, gold, RULED)["fact"] == 1
    decided = answer.replace("kind: why", "kind: decision")
    assert decided != answer
    assert retrogold.score(decided, gold, RULED)["fact"] == 1
    for was, now in (("label: important", "label: investigation"),
                     ("kind: why", "kind: convention")):
        changed = answer.replace(was, now)
        assert changed != answer
        assert retrogold.score(changed, gold, RULED)["fact"] == 0, now


def test_the_gold_itself_gets_full_marks():
    for case in retrogold.cases(CASES):
        got = retrogold.score(retrogold.answer_of(case),
                              retrogold.gold_of(case), case)
        full = 4 if case.name in FAILED else 1
        assert (got["score"], got["passed"]) == (full, True), (case.name, got)


def test_the_stale_readme_is_handed_to_the_retro_and_its_edit_is_made():
    prompt = retrogold.prompt_of(STALE)
    part = prompt.split("docs that name a file or a name this run changed,"
                        " each to confirm current or edit:\n")[1]
    assert part.split("\n\n")[0].split("\n") == [
        "- README.md names --file:",
        "  README.md:7: pass --file out.txt to write the counts to a file"
        " instead of stdout."]
    items, _ = upkeep.parse(retrogold.answer_of(STALE))
    [(verb, value, fields)] = items
    assert (verb, value) == ("edit", "README.md")
    assert retrogold.edit_refusal(STALE, value, fields) == ""


def test_an_edit_that_keeps_the_old_flag_or_quotes_a_new_one_scores_nothing():
    gold = retrogold.gold_of(STALE)
    answer = retrogold.answer_of(STALE)
    kept = answer.replace("after: pass --output out.txt",
                          "after: pass --file or --output out.txt")
    assert retrogold.score(kept, gold, STALE)["edit"] == 0
    made_up = answer.replace("after: pass --output out.txt",
                             "after: pass --output out.txt or --to")
    assert retrogold.score(made_up, gold, STALE)["edit"] == 0
    elsewhere = answer.replace("edit: README.md", "edit: TASK.md")
    assert retrogold.score(elsewhere, gold, STALE) == dict(
        edit=0, score=0, passed=False, reader=None)
    assert retrogold.score(answer, gold, STALE)["edit"] == 1


def test_every_gold_fact_is_one_the_runner_would_write():
    for case in retrogold.cases(CASES):
        if "fact" not in WANTED.get(case.name, {"fact"}):
            continue
        items, _ = upkeep.parse(retrogold.answer_of(case))
        found = [(v, val, f) for v, val, f in items if v == "fact"]
        assert found, case.name
        for verb, value, fields in found:
            assert retrogold.refusal(case, verb, value, fields) == "", \
                case.name


def test_a_fact_the_runner_would_refuse_scores_no_fact_point():
    case = CASES / "cross-file"
    gold = retrogold.gold_of(case)
    answer = retrogold.answer_of(case)
    unbacked = answer.replace('TASK.md:4 "every user-facing error is raised'
                              ' as LogcountError"',
                              'TASK.md:4 "errors are printed where they'
                              ' happen"')
    assert unbacked != answer
    got = retrogold.score(unbacked, gold, case)
    assert (got["fact"], got["score"]) == (0, 3)
    no_why = "\n".join(l for l in answer.split("\n")
                       if not l.strip().startswith("why: TASK.md"))
    assert retrogold.score(no_why, gold, case)["fact"] == 0
    place = case / "place"
    before = sorted(p.relative_to(place).as_posix()
                    for p in place.rglob("*"))
    retrogold.score(answer, gold, case)
    assert sorted(p.relative_to(place).as_posix()
                  for p in place.rglob("*")) == before


def test_an_answer_that_sends_the_change_to_the_wrong_file_gets_nothing():
    case = CASES / "cross-file"
    wrong = retrogold.answer_of(case).replace("logcount/reader.py",
                                              "logcount/cli.py")
    got = retrogold.score(wrong, retrogold.gold_of(case), case)
    assert got["change"] == 0
    assert (got["score"], got["passed"]) == (0, False)


def test_each_item_is_scored_on_its_own():
    case = CASES / "refactor"
    gold = retrogold.gold_of(case)
    answer = retrogold.answer_of(case)
    no_cause = answer.replace("round", "trunc")
    assert retrogold.score(no_cause, gold, case)["cause"] == 0
    assert retrogold.score(no_cause, gold, case)["score"] == 3
    wrong_seq = answer.replace("## seq 2 worker.md", "## seq 3 patcher.md")
    assert retrogold.score(wrong_seq, gold, case)["failed"] == 0
    wrong_kind = answer.replace("kind: convention", "kind: decision")
    assert retrogold.score(wrong_kind, gold, case)["fact"] == 0
    assert retrogold.score("", gold, case) == dict(
        retrogold.score("", gold, case), score=0, passed=False)


def test_a_fact_in_a_block_that_does_not_parse_scores_nothing():
    case = CASES / "cross-file"
    broken = retrogold.answer_of(case).replace("END FACTS", "")
    assert retrogold.score(broken, retrogold.gold_of(case), case)["fact"] == 0


def test_the_record_s_prompt_is_the_one_a_run_hands_the_retro():
    prompt = retrogold.prompt_of(CASES / "cross-file")
    assert "- seq 3 worker.md, gate failed: " in prompt
    assert "test_unreadable_one_line" in prompt
    assert "- seq 3 worker.md did: " in prompt
    assert "files this run changed, from git:\n- logcount/count.py\n" in prompt
    assert "new facts this run may write:\n- 3\n" in prompt
    assert "handoff.md:" in prompt


def a_set(tmp_path, replies, live=False):
    folder = tmp_path / "set"
    folder.mkdir()
    for case in retrogold.cases(CASES):
        target = folder / case.name
        for path in case.rglob("*"):
            if path.is_file():
                (target / path.relative_to(case)).parent.mkdir(
                    parents=True, exist_ok=True)
                (target / path.relative_to(case)).write_bytes(
                    path.read_bytes())
    provider = {"provider": "claude" if live else "fake",
                "replies": {"retro.md": replies}}
    (folder / "bench.yaml").write_text(json.dumps({"provider": provider}),
                                       encoding="utf-8")
    return folder


def test_step_mode_asks_the_retro_alone_on_each_record_and_scores_it(
        tmp_path, capsys):
    gold = [retrogold.answer_of(c) for c in retrogold.cases(CASES)]
    folder = a_set(tmp_path, [g for g in gold for _ in range(2)])
    out = tmp_path / "scores.json"
    assert bench.main(["--retro", str(folder), "--k", "2", "--out",
                       str(out)]) == 0
    kept = json.loads(out.read_text(encoding="utf-8"))
    assert [(r["case"], r["k"], r["score"]) for r in kept["runs"]] == [
        (n, k, 4 if n in FAILED else 1) for n in NAMES for k in (1, 2)]
    assert kept["summary"] == {"cases": 6, "passed": 6, "k": 2}
    said = capsys.readouterr().out
    assert "6 of 6 cases passed at 2 of 2" in said
    assert "renamed-flag k1: 1 of 1" in said


def test_a_case_passes_only_when_every_repeat_does(tmp_path, capsys):
    gold = [retrogold.answer_of(c) for c in retrogold.cases(CASES)]
    replies = [gold[0], "## change first\n- none\n"] + [
        g for g in gold[1:] for _ in range(2)]
    folder = a_set(tmp_path, replies)
    out = tmp_path / "scores.json"
    assert bench.main(["--retro", str(folder), "--k", "2", "--out",
                       str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["summary"][
        "passed"] == 5


class Counted(Provider):
    """answers each record with its gold and says what it used."""

    name = "counted"

    def ask(self, prompt, timeout=None):
        case = Path(self.where).parent
        return Reply(retrogold.answer_of(case), cost=0.02,
                     usage=Usage({"input_tokens": 1000, "output_tokens": 200,
                                  "cache_read_input_tokens": 300}))


def test_step_mode_keeps_the_tokens_and_seconds_of_every_answer(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(base.registry, Counted.name, Counted)
    folder = a_set(tmp_path, [])
    (folder / "bench.yaml").write_text(json.dumps(
        {"provider": {"provider": "counted"}}), encoding="utf-8")
    out = tmp_path / "scores.json"
    assert bench.main(["--retro", str(folder), "--live", "--out",
                       str(out)]) == 0
    runs = json.loads(out.read_text(encoding="utf-8"))["runs"]
    assert [r["tokens"] for r in runs] == [
        {"counted": True, "input": 1300, "output": 200, "cache_read": 300,
         "cache_creation": 0}] * 6
    assert all(isinstance(r["seconds"], float) and r["seconds"] >= 0
               for r in runs)
    assert [r["cost"] for r in runs] == [0.02] * 6
    (tmp_path / "fake").mkdir()
    fake = a_set(tmp_path / "fake", [retrogold.answer_of(CASES / "layered")])
    assert bench.main(["--retro", str(fake), "--out", str(out)]) == 0
    runs = json.loads(out.read_text(encoding="utf-8"))["runs"]
    assert all(r["tokens"] == {"counted": False} for r in runs)


def test_step_mode_on_a_real_model_runs_only_with_live(tmp_path, capsys):
    folder = a_set(tmp_path, [], live=True)
    assert bench.main(["--retro", str(folder)]) == 1
    assert "--live" in capsys.readouterr().out
