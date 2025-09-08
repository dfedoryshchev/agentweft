# run this by hand: python tests/check_frontmatter.py
import sys

sys.path.insert(0, ".")
import runner

cfg = runner.config("weekly-digest")
assert cfg["name"] == "weekly digest", cfg
assert cfg["steps"][0]["role"] == "planner", cfg
assert cfg["note"].startswith("read on a sunday"), cfg

print("ok")
