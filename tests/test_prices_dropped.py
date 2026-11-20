"""a price table of the person's that is not read is said, never dropped in
silence.

agentweft started in the run's place, or the repo it is in, prices on the
shipped table: a `./prices.yaml` there is the project's, and a cheaper one
would loosen the money cap. when the run's place is not known at load (a
flow's `workdir:`, a resume started without `--workdir`) that holds for the
person's own folder too, so the table they keep there is not read; the run
says which table it priced on and why, once.
"""
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import prices
from agentweft.runner import settings


def test_a_prices_yaml_left_unread_is_said_once(tmp_path, monkeypatch,
                                                capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PRICES", raising=False)
    (tmp_path / "prices.yaml").write_text("models: {}\n", encoding="utf-8")
    monkeypatch.setattr(settings, "STARTED_IN_PLACE", True)
    monkeypatch.setattr(prices, "SAID", set())
    assert prices.where_from() == prices.SHIPPED
    assert prices.where_from() == prices.SHIPPED
    out = capsys.readouterr().out
    assert out.count("prices.yaml is not read") == 1
    assert "the shipped table prices this run" in out


def test_no_line_when_there_is_no_table_to_leave_unread(tmp_path, monkeypatch,
                                                        capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PRICES", raising=False)
    monkeypatch.setattr(settings, "STARTED_IN_PLACE", True)
    monkeypatch.setattr(prices, "SAID", set())
    assert prices.where_from() == prices.SHIPPED
    assert capsys.readouterr().out == ""
    (tmp_path / "prices.yaml").write_text("models: {}\n", encoding="utf-8")
    monkeypatch.setattr(settings, "STARTED_IN_PLACE", False)
    assert prices.where_from().name == "prices.yaml"
    assert capsys.readouterr().out == ""
