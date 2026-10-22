"""a second run on the same repo: run 1 leaves facts, run 2 is handed them,
and the twin is run 2 again with no fact. run 2 is held to the pair's
convention by a check of its own, and every run to the probation rules set
before any pair ran."""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.bench import __main__ as bench
from agentweft.providers import Provider, Reply, base
from agentweft.runner import prompts

NL = chr(10)
CODE = NL.join(["def parse(line):", "    if not line:",
                "        raise ValueError('empty')", "    return line.split()",
                ""])
KEEP = NL.join(["## change first", "- none", "", "FACTS", "fact:",
                "  scope: pkg/", "  kind: convention",
                "  claim: a module under pkg/ raises on bad input, never"
                " prints", "  why: one error path for the caller",
                '  source: seq 1 worker.md; evidence: pkg/a.py:3 "raise'
                " ValueError('empty')" + '"', "END FACTS", ""])
NOTHING = "## change first" + NL + "- none" + NL
QUIET = NL.join(["def count(line):", "    return len(line.split())", ""])
LOUD = NL.join(["def count(line):", "    print('counting')",
                "    return len(line.split())", ""])
HIDDEN = NL.join(["import os", "import sys", "",
                  "sys.path.insert(0, os.environ['TASK_REPO'])", "", "",
                  "def test_count():", "    from pkg import b", "",
                  "    assert b.count('a b') == 2", ""])
CHECK = NL.join(["import os", "import pathlib", "import sys", "",
                 "root = pathlib.Path(os.environ['TASK_REPO']) / 'pkg'",
                 "sys.exit(1 if any('print(' in p.read_text() for p in"
                 " root.glob('*.py')) else 0)", ""])


class Pairing(Provider):
    """run 1's retro keeps a fact; run 2's worker writes pkg/b.py, loud or
    quiet; every later retro keeps nothing."""

    name = "pairing"
    loud = True
    retros = 0
    saw = []

    def at(self, step, task):
        self.step = step

    def ask(self, prompt, timeout=None):
        where = Path(self.where)
        if getattr(self, "step", None) == "retro.md":
            Pairing.retros = Pairing.retros + 1
            return Reply(KEEP if Pairing.retros == 1 else NOTHING)
        if "count the words" in prompt:
            Pairing.saw.append((bool(list((where / "facts").rglob("*.md"))),
                                (where / "facts" / "rates.json").is_file(),
                                (where / "pkg" / "facts").is_dir()))
            (where / "pkg" / "b.py").write_text(
                LOUD if Pairing.loud else QUIET, encoding="utf-8")
        return Reply("done" + NL)


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=NL)


@pytest.fixture
def a_set(tmp_path, monkeypatch):
    flows = tmp_path / "flows"
    put(flows / "one-step" / "flow.yaml", yaml.safe_dump(
        {"name": "one-step", "retro": True,
         "steps": [{"role": "worker", "prompt": "worker.md"}],
         "timeout": 60, "journal": False}))
    put(flows / "one-step" / "worker.md", "# worker" + NL + NL + "do this:"
        + NL + NL + "{TASK}" + NL)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(flows)])
    monkeypatch.setitem(base.registry, Pairing.name, Pairing)
    Pairing.retros = 0
    Pairing.loud = True
    Pairing.saw = []
    folder = tmp_path / "set"
    put(folder / "bench.yaml", yaml.safe_dump(
        {"flow": "one-step", "provider": {"provider": "pairing"}}))
    pair = folder / "errors"
    put(pair / "repo" / "pkg" / "__init__.py", "")
    put(pair / "repo" / "pkg" / "a.py", CODE)
    put(pair / "first.md", "make pkg/a.py refuse an empty line" + NL)
    put(pair / "second.md", "count the words: add pkg/b.py beside pkg/a.py"
        + NL)
    put(pair / "hidden" / "test_count.py", HIDDEN)
    put(pair / "check.py", CHECK)
    put(pair / "gold.yaml", yaml.safe_dump(
        {"trail": [{"scope": ["pkg/"], "kind": "convention"}],
         "false": [{"scope": ["pkg/"], "words": ["prints the error"]}],
         "convention": {"scope": ["pkg/"], "check": ["python", "check.py"]}}))
    return folder


def scored(folder, tmp_path, *more):
    out = tmp_path / "pairs.json"
    assert bench.main(["--pairs", str(folder), "--live", "--out", str(out)]
                      + list(more)) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_a_run_2_that_breaks_a_convention_it_was_handed_is_contradicted(
        a_set, tmp_path, capsys):
    got = scored(a_set, tmp_path)
    [row] = got["runs"]
    first = row["first"]
    assert (first["facts_written"], first["trail_found"],
            first["false_facts"]) == (1, 1, [])
    lane = row["second"]["lane"]
    assert lane["facts_attached"] == [["worker.md", "F-0001"]]
    assert lane["facts_used"] == [["worker.md", "F-0001"]]
    assert lane["changed"] == ["pkg/b.py"]
    assert lane["convention"] == "contradicted"
    assert lane["core_correct"] is True
    assert "twin" not in row["second"]
    assert got["summary"]["lane"]["conventions"]["contradicted"] == 1
    assert "probation holds" in capsys.readouterr().out


def test_a_run_2_that_keeps_the_convention_is_honoured(a_set, tmp_path):
    Pairing.loud = False
    lane = scored(a_set, tmp_path)["runs"][0]["second"]["lane"]
    assert lane["convention"] == "honoured"


def test_the_twin_is_the_same_run_2_with_no_fact_handed(a_set, tmp_path):
    got = scored(a_set, tmp_path, "--twin")
    arms = got["runs"][0]["second"]
    assert arms["lane"]["facts_attached"] == [["worker.md", "F-0001"]]
    assert arms["twin"]["facts_attached"] == []
    assert arms["twin"]["changed"] == ["pkg/b.py"]
    assert arms["twin"]["convention"] == "contradicted"
    assert set(got["summary"]) >= {"lane", "twin", "probation"}


def test_the_twin_runs_without_the_facts_run_1_left_on_disk(a_set,
                                                            tmp_path):
    put(a_set / "errors" / "repo" / "pkg" / "facts" / "rates.json", "{}")
    put(a_set / "errors" / "repo" / "facts" / "rates.json", "{}")
    scored(a_set, tmp_path, "--twin")
    assert Pairing.saw == [(True, True, True), (False, True, True)]


def test_a_set_whose_pair_names_no_convention_is_refused(a_set, tmp_path,
                                                         capsys):
    gold = a_set / "errors" / "gold.yaml"
    gold.write_text(yaml.safe_dump({"trail": []}), encoding="utf-8")
    assert bench.main(["--pairs", str(a_set), "--live"]) == 1
    assert "names no convention" in capsys.readouterr().out


def test_a_real_provider_runs_a_pair_set_only_with_live(a_set, capsys):
    assert bench.main(["--pairs", str(a_set)]) == 1
    assert "--live" in capsys.readouterr().out


def a_row(first, second=0, attached=(), used=(), false=()):
    return {"pair": "p", "attempt": 1,
            "first": {"facts_written": first, "false_facts": list(false)},
            "second": {"lane": {"facts_written": second,
                                "facts_attached": list(attached),
                                "facts_used": list(used)}}}


def test_the_probation_scorer_flags_a_run_with_four_new_facts_as_spam():
    from agentweft.bench import pairs

    said = pairs.probation([a_row(3), a_row(4)])
    assert (said["most"], said["spam"], said["holds"]) == (4, 1, False)
    assert pairs.probation([a_row(3, 3)])["holds"] is True


def test_fewer_than_one_in_four_attached_facts_used_fails_probation():
    from agentweft.bench import pairs

    handed = [["worker.md", "F-%04d" % n] for n in range(1, 6)]
    under = pairs.probation([a_row(1, attached=handed, used=handed[:1])])
    assert (under["used"], under["attached"], under["used_ok"],
            under["holds"]) == (1, 5, False, False)
    held = pairs.probation([a_row(1, attached=handed[:4], used=handed[:1])])
    assert held["used_ok"] is True and held["holds"] is True
    none = pairs.probation([a_row(1)])
    assert none["used_ok"] is None and none["holds"] is True


def test_a_written_fact_is_read_against_the_gold_trail_and_its_false_ones():
    from agentweft.bench import pairs
    from agentweft.orchestrate import facts

    gold = {"trail": [{"scope": ["pkg/"], "kind": "convention"}],
            "false": [{"scope": ["pkg/cli.py"], "words": ["prints", "error"]}]}
    kept = facts.Fact("F-0001", "live", [("scope", "pkg"),
                                         ("kind", "convention"),
                                         ("claim", "pkg raises, never prints")])
    wrong = facts.Fact("F-0002", "live", [("scope", "pkg\\cli.py"),
                                          ("kind", "why"),
                                          ("claim", "cli.py Prints the error"
                                           " itself")])
    assert pairs.against_gold([kept, wrong], gold) == ([0], ["F-0002"])
    assert pairs.against_gold([wrong], gold) == ([], ["F-0002"])


def test_a_fact_the_gold_names_false_kills_the_write_path():
    from agentweft.bench import pairs

    said = pairs.probation([a_row(1, false=["F-0002"])])
    assert said["kill"] is True and said["holds"] is False
    assert "killed until fixed" in "\n".join(pairs.lines(
        {"pairs": 1, "k": 1, "probation": said}))
