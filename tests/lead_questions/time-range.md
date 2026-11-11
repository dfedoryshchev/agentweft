HANDOFF
DID:
- Planned both features as behaviours a test can check: `filter --since/--until` and a new `top` command. None contradicts TASK.md; both add to it.
QUESTION: Must T be a real date and time, with offset hours 00-23 and minutes 00-59 like log times at TASK.md:47-48, and is a T whose UTC value falls outside the years 0001-9999 an `invalid time`?
RECOMMEND: yes to all three. Mirror TASK.md:47-50 and give `error: invalid time: <T>` for any of them, which keeps the time rules consistent.
SIZE: one function in logsift/filters.py and a few lines in TASK.md.
END HANDOFF
