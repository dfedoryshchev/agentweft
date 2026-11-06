"""a QUESTION the lead's own handoff asks is decided or goes to the person.

the lead is the step that decides what other steps ask. when its own
handoff asks a QUESTION with a RECOMMEND and cites no line of the place, the
recommendation is the lead's decision: it is put on record in decisions.md
as the lead's, every later step gets it, and it is no open question on the
handoff. one that cites a line of the place, a spec line the person rules
on, or that recommends nothing, parks the run at the lead for the person.
`QUESTION: none` asks nothing, and a QUESTION of a step that is not the lead
rides on the handoff as before.
"""
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import engine, prompts, stops

NL = chr(10)
ASK = "should a write through the client clear the cached list?"
REC = "clear the cached list on a successful write"


def block(question, recommend=None):
    lines = ["HANDOFF", "DID:", "- set out the cache", "QUESTION: " + question]
    if recommend:
        lines += ["RECOMMEND: " + recommend, "SIZE: 2 lines in api.py"]
    return NL.join(["- behaviour: the list is cached", "  file: api.py", ""]
                   + lines + ["END HANDOFF", ""])


def a_flow(tmp_path, monkeypatch):
    d = tmp_path / "flows" / "led"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(NL.join([
        "name: led", "lead: planner", "steps:", "  - role: planner",
        "    prompt: planner.md", "  - role: worker", "    prompt: worker.md",
        ""]), encoding="utf-8")
    for role in ("planner", "worker"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (tmp_path / "TASK.md").write_text("# task" + NL + "the list is cached"
                                      + NL, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])


def answering(monkeypatch, planner, worker="done" + NL):
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        return (planner if step == "planner.md" else worker), False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force"])
    return engine.main()


def folder(tmp_path):
    [found] = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    return found


def decision(found):
    text = (found / "handoff.md").read_text(encoding="utf-8")
    return text.split("## the one decision")[1].split(NL + "##")[0]


def test_the_lead_s_own_recommendation_is_its_decision(tmp_path,
                                                        monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, block(ASK, REC))
    assert run(monkeypatch) == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]
    [entry] = decisions.read(tmp_path)
    assert entry.decided == "planner.md decided for planner.md: " + REC
    assert ASK in entry.why
    assert REC in dict(asked)["worker.md"]
    assert "nothing waits on you" in decision(folder(tmp_path))


def test_a_lead_question_citing_a_line_of_the_place_parks(tmp_path,
                                                           monkeypatch):
    a_flow(tmp_path, monkeypatch)
    cited = "TASK.md:2 says the list is cached; " + ASK
    asked = answering(monkeypatch, block(cited, REC))
    assert run(monkeypatch) == stops.EXIT_STOP
    assert [s for s, _ in asked] == ["planner.md"]
    question = (folder(tmp_path) / "question.md").read_text(encoding="utf-8")
    assert ASK in question and REC in question
    assert decisions.read(tmp_path) == []


def test_a_lead_question_with_no_recommendation_parks(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, block(ASK))
    assert run(monkeypatch) == stops.EXIT_STOP
    assert [s for s, _ in asked] == ["planner.md"]
    assert ASK in (folder(tmp_path) / "question.md").read_text(
        encoding="utf-8")


def test_a_lead_recommendation_that_names_a_test_or_quotes_parks(
        tmp_path, monkeypatch):
    for rec in ("rewrite test_cache_is_kept to clear it",
                'change "the list is cached" to say it clears'):
        place = tmp_path / rec.split()[0]
        place.mkdir()
        a_flow(place, monkeypatch)
        asked = answering(monkeypatch, block(ASK, rec))
        assert run(monkeypatch) == stops.EXIT_STOP, rec
        assert [s for s, _ in asked] == ["planner.md"], rec
        assert decisions.read(place) == [], rec


def test_a_lead_question_of_none_asks_nothing(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, block("none"))
    assert run(monkeypatch) == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]
    assert decisions.read(tmp_path) == []


def test_a_question_of_a_step_that_is_not_the_lead_rides_as_before(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    worker = NL.join(["built it", "", "HANDOFF", "DID:", "- built it",
                      "QUESTION: " + ASK, "RECOMMEND: " + REC,
                      "SIZE: 2 lines in api.py", "END HANDOFF", ""])
    asked = answering(monkeypatch, block("none"), worker)
    assert run(monkeypatch) == stops.EXIT_OK
    assert decisions.read(tmp_path) == []
    assert ASK in decision(folder(tmp_path))
