# planner

read the .md files in {INBOX} modified in the last 7 days. do not summarise
anything yet, and do not write the digest.

## what to give me

one line per file, in this shape:

    <filename> | <list> | <why, under ten words>

where list is one of: changed, needs-me, can-wait.

## how to decide

- needs-me means a question addressed to the reader, a date to hit, or money.
  not "this is important".
- can-wait means it will matter in a month, not this week.
- changed is everything else that actually moved.

## what not to do

- do not open files that have not changed in 7 days
- do not merge two files into one line
- if a file is empty or unreadable, say so on its line and move on
- if nothing changed at all, print "nothing to report" and stop
