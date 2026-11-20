"""a merge ticket is exempt from the fact check by its kind.

a nice-to-do that names two or more of the run's new tests that look alike
(`duplicates.py`) asks for them to be merged into one. a fact's check is one
grep and its exit code: it cannot count, and a grep for the named tests keeps
holding after a merge that keeps one of the names, so such a check only
finds the ticket's own line (a measured run's ticket was refused so). the
ticket is kept without its check and says so, `unchecked: a merge ticket`;
any other nice-to-do's check is read as before.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.guardrails import factsguard
from agentweft.orchestrate import facts
from agentweft.runner import upkeep

from test_retro_maintains import block, put

NL = chr(10)
REL = "tests/test_stats.py"
MEAN = REL + "::test_stats_mean_half_rounds_up"
PERCENT = REL + "::test_stats_percent_half_rounds_up"
SOURCE = NL.join(["from stats import mean, percent", "", "",
                  "def test_stats_mean_half_rounds_up():",
                  "    assert mean([0.125]) == 0.13", "", "",
                  "def test_stats_percent_half_rounds_up():",
                  "    assert percent(0.125) == 13.0", ""])


def ticket(claim, check):
    return NL.join([
        "fact:", "  scope: " + REL, "  kind: nice-to-do", "  label: none",
        "  claim: " + claim,
        "  why: both check one rounding through one helper",
        '  source: seq 3 tester.md; evidence: ' + REL
        + ':8 "def test_stats_percent_half_rounds_up():"',
        "  anchor: " + REL + ":8-8", "  check: " + check])


MERGE = ("merge test_stats_mean_half_rounds_up and"
         " test_stats_percent_half_rounds_up into one parametrized test")
OWN_LINE = ('grep -n -F "def test_stats_percent_half_rounds_up" ' + REL
            + " exits 0")


def kept_up(tmp_path, said, alike=True):
    put(tmp_path, REL, SOURCE)
    store = factsguard.Store(tmp_path)
    store.alike = [(0.9, REL, [MEAN, PERCENT])] if alike else []
    done = upkeep.maintain(store, factsguard.Record(tmp_path), said, "r")
    return done, facts.read(tmp_path)


def test_a_merge_ticket_is_kept_without_its_check_by_kind(tmp_path):
    done, [fact] = kept_up(tmp_path, block(ticket(MERGE, OWN_LINE)))
    assert done.tickets == [fact.id]
    assert fact.get("check") == ""
    assert fact.get("unchecked") == "a merge ticket"
    assert "(kept without its check; a merge ticket)" in done.lines[0]


def test_a_merge_ticket_with_no_check_says_nothing_of_one(tmp_path):
    item = NL.join(l for l in ticket(MERGE, OWN_LINE).split(NL)
                   if not l.startswith("  check:"))
    done, [fact] = kept_up(tmp_path, block(item))
    assert fact.get("unchecked") == "" and fact.get("check") == ""


def test_another_nice_to_do_s_check_is_read_as_before(tmp_path):
    claim = "assert the printed percent in test_stats_percent_half_rounds_up"
    done, [fact] = kept_up(tmp_path, block(ticket(claim, OWN_LINE)))
    assert fact.get("unchecked").startswith(
        "its check was refused: the check only finds the fact's own anchored"
        " line")


def test_with_no_group_of_alike_tests_a_merge_claim_is_checked_as_before(
        tmp_path):
    done, [fact] = kept_up(tmp_path, block(ticket(MERGE, OWN_LINE)),
                           alike=False)
    assert fact.get("unchecked").startswith("its check was refused: ")
