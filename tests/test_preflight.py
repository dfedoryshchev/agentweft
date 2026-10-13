import sys

sys.path.insert(0, ".")
from agentweft.mcp import preflight

RANKING = "src/hooks.ts 0.94" + chr(10) + "src/util.ts 0.11" + chr(10) + "junk"


def test_a_ranking_parses_and_skips_junk():
    r = preflight.parse_ranking(RANKING)
    assert r["src/hooks.ts"] == 0.94
    assert "junk" not in r


def test_a_hot_file_is_found():
    hot = preflight.check("i will rewrite src/hooks.ts", RANKING)
    assert hot and hot[0][0] == "src/hooks.ts"


def test_a_cold_file_is_not_flagged():
    assert preflight.check("touching src/util.ts only", RANKING) == []


def test_no_ranking_means_nothing_is_flagged():
    assert preflight.check("src/hooks.ts", "") == []


def test_the_threshold_is_respected():
    assert preflight.check("src/hooks.ts", RANKING, threshold=0.99) == []


PKG = "pkg/a.py 0.9" + chr(10) + "pkg/b.py 0.2"


def test_a_backslash_step_finds_a_forward_slash_ranking():
    assert preflight.check("i will rewrite pkg\\a.py", PKG) == [("pkg/a.py", 0.9)]


def test_a_backslash_ranking_is_found_by_a_forward_slash_step():
    ranking = "pkg\\a.py 0.9"
    assert preflight.check("i will rewrite pkg/a.py", ranking) == [("pkg\\a.py", 0.9)]


def test_mixed_separators_in_one_path_still_match():
    ranking = "pkg/sub/a.py 0.9"
    assert preflight.check("editing pkg\\sub/a.py", ranking) == [("pkg/sub/a.py", 0.9)]


def test_a_leading_dot_backslash_still_matches():
    assert preflight.check("editing .\\pkg\\a.py", PKG) == [("pkg/a.py", 0.9)]


def test_a_backslash_cold_file_is_not_flagged():
    assert preflight.check("touching pkg\\b.py only", PKG) == []


def test_files_mentioned_finds_each_path_once():
    found = preflight.files_mentioned("first src/hooks.ts, then README.md")
    assert found == {"src/hooks.ts", "README.md"}


def test_files_mentioned_counts_one_path_spelled_both_ways_once():
    assert preflight.files_mentioned("pkg\\a.py and pkg/a.py") == {"pkg/a.py"}


def test_a_leading_dot_slash_is_dropped_not_turned_into_a_root():
    assert preflight.files_mentioned("editing ./pkg/a.py.") == {"pkg/a.py"}
    assert preflight.files_mentioned("then ../pkg/b.py") == {"pkg/b.py"}


def test_a_path_matches_only_from_the_start_of_a_segment():
    assert preflight.check("i will rewrite mysrc/hooks.ts", RANKING) == []
    assert preflight.check("i will rewrite hooks.ts", RANKING) == \
        [("src/hooks.ts", 0.94)]


def test_a_ranked_path_inside_a_longer_one_is_found():
    assert preflight.check("editing app/src/hooks.ts", RANKING) == \
        [("src/hooks.ts", 0.94)]


def test_files_mentioned_on_nothing_is_empty():
    assert preflight.files_mentioned("") == set()
    assert preflight.files_mentioned(None) == set()


def test_the_warning_names_the_file_and_asks_for_a_reason():
    text = preflight.as_warning(preflight.check("src/hooks.ts", RANKING))
    assert "src/hooks.ts" in text
    assert "smaller change" in text
