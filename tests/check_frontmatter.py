# run this by hand: python tests/check_frontmatter.py
import sys

sys.path.insert(0, ".")
import runner

fm = runner.frontmatter("weekly-digest")
assert fm["name"] == "weekly digest", fm
assert "planner" in fm["steps"], fm
assert fm["note"].startswith("read on a sunday"), fm

print("ok")
