# planner

here is a list of source files. do not read them all.

give me a plan: which files are worth reading, one task each, in this shape:

    TASK: <path>
    WHY: <why it matters, under ten words>
    FILES:
    - <path>

a blank line between tasks. FILES names every file the task touches, one per
line.

put the entry points and the biggest files first. skip generated files, tests,
and anything vendored.

at most 20 tasks. a repo with four hundred files does not get four hundred
workers - pick the twenty that decide what the thing is.
