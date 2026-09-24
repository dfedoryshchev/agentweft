import datetime
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions

AT = datetime.datetime(2026, 9, 24, 14, 3)


def test_an_entry_is_the_decision_as_a_heading_and_the_why_under_it():
    assert decisions.lines("keep three retries", "the limit resets each minute", AT) == [
        "## 2026-09-24 14:03  keep three retries",
        "",
        "the limit resets each minute",
        "",
    ]


def test_a_decision_with_no_why_is_refused():
    with pytest.raises(ValueError) as e:
        decisions.lines("keep three retries", "  \n", AT)
    assert "keep three retries" in str(e.value)


def test_an_empty_decision_is_refused():
    with pytest.raises(ValueError):
        decisions.lines("", "because", AT)


def test_the_decision_is_one_line_and_the_why_can_be_many():
    with pytest.raises(ValueError):
        decisions.lines("keep three\nretries", "because", AT)
    assert decisions.lines("keep three retries", "one\ntwo", AT)[2:4] == ["one", "two"]


def test_it_writes_into_the_folder_it_is_given(tmp_path):
    path = decisions.record(tmp_path / "docs", "keep three retries", "because", AT)
    assert path == tmp_path / "docs" / "decisions.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# decisions\n\n## 2026-09-24 14:03  keep three retries")
    assert text.endswith("\n")


def test_a_second_decision_is_appended_and_the_first_stays(tmp_path):
    decisions.record(tmp_path, "keep three retries", "the limit resets each minute", AT)
    later = AT + datetime.timedelta(days=2)
    decisions.record(tmp_path, "drop to two retries", "three was hiding a real outage", later)
    text = (tmp_path / "decisions.md").read_text(encoding="utf-8")
    assert text.count("# decisions") == 1
    assert text.index("keep three retries") < text.index("drop to two retries")


def test_what_was_written_reads_back_the_same(tmp_path):
    decisions.record(tmp_path, "keep three retries", "the limit resets\neach minute", AT)
    decisions.record(tmp_path, "no cache", "it went stale twice", AT)
    back = decisions.read(tmp_path)
    assert [(d.at, d.decided, d.why) for d in back] == [
        (AT, "keep three retries", "the limit resets\neach minute"),
        (AT, "no cache", "it went stale twice"),
    ]


def test_no_log_is_no_decisions(tmp_path):
    assert decisions.read(tmp_path) == []


def test_a_hand_written_entry_reads_back_too(tmp_path):
    (tmp_path / "decisions.md").write_text(
        "# decisions\n\nsome notes first\n\n"
        "## 2026-01-02 09:00  one repo, not two\n\n"
        "the two halves were the same shape.\n\n- and a list\n",
        encoding="utf-8")
    [d] = decisions.read(tmp_path)
    assert d.decided == "one repo, not two"
    assert d.why == "the two halves were the same shape.\n\n- and a list"
