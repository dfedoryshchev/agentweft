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


def test_the_warning_names_the_file_and_asks_for_a_reason():
    text = preflight.as_warning(preflight.check("src/hooks.ts", RANKING))
    assert "src/hooks.ts" in text
    assert "smaller change" in text
