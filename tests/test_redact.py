"""a provider key that reaches an answer, a gate's output or an error is
never written into a recording or the run's record."""
import json
import sys

sys.path.insert(0, ".")
from agentweft.evals import recording
from agentweft.guardrails import redact
from agentweft.providers.base import Provider, Reply
from agentweft.runner import engine, prompts, resume, state

# built from pieces so no whole key sits in the source
KEY = "sk" + "-ant-" + "api03-" + "Ab1_" * 6 + "-zz"
SAID = "the value is " + KEY + " and nothing else\n"


class Says(Provider):
    name = "says"

    def ask(self, prompt, timeout=None):
        return Reply(SAID, detail="failed with " + KEY)


def test_a_key_is_redacted_whatever_surrounds_it():
    assert redact.redact(SAID) == "the value is sk-ant-REDACTED and nothing" \
        " else\n"
    assert redact.redact('{"k": "' + KEY + '"}') == \
        '{"k": "sk-ant-REDACTED"}'
    assert redact.redact("x" + KEY) == "xsk-ant-REDACTED"


def test_text_with_no_key_is_left_as_it_is():
    for text in ("", "sk-ant-", "a sk-ant- b", "task-ant-x", None):
        assert redact.redact(text) == text


def test_a_recording_keeps_no_key(tmp_path):
    rec = recording.Recorder(Says())
    rec.at("worker.md", None)
    assert rec.ask("go").text == SAID
    path = tmp_path / recording.FILE
    rec.save(path)
    text = path.read_text(encoding="utf-8")
    assert KEY not in text
    [call] = json.loads(text)["calls"]
    assert call["say"] == redact.redact(SAID)
    assert call["detail"] == "failed with sk-ant-REDACTED"


def test_the_run_s_record_keeps_no_key(tmp_path, monkeypatch):
    d = tmp_path / "flows" / "leaky"
    d.mkdir(parents=True)
    (d / "worker.md").write_text("# worker\n\ndo it.\n", encoding="utf-8")
    (d / "instructions.md").write_text("the flow.\n", encoding="utf-8")
    (d / "flow.yaml").write_text(
        "name: leaky\nsteps:\n  - role: worker\n    prompt: worker.md\n"
        "provider:\n  provider: fake\n  reply: " + json.dumps(SAID) + "\n",
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", "leaky", "--force"])
    monkeypatch.setattr(resume, "JOURNAL", None)
    assert engine.main() == 0
    written = [p for p in state.RUNS.rglob("*") if p.is_file()]
    seen = "".join(p.read_text(encoding="utf-8") for p in written)
    assert "sk-ant-REDACTED" in seen
    for p in written:
        assert KEY not in p.read_text(encoding="utf-8"), p
