find the cause before anything is written, and everything it reaches. do not
fix it and change nothing in the place: the steps after you write the test and
the patch, from what you say here.

what was reported:

{TASK}

read the code until you can say why it happens. a cause with "might" or
"could" in it has not been found yet. run what shows it if you can.

answer with these, each label at the start of its own line:

    CAUSE: <file>:<line> - why it does what it does
    SITES:
    - <file>:<function> - <one clause: why it shares the cause>
    FEEDS:
    - <a command or caller the code you would change feeds>
    RELATED:
    - <a different defect you saw on the way, or none>
    ROOTED: yes
    RULED OUT:
    - <a cause you checked and dropped> - <what showed it was not that>
    REPRO: <the command you ran to see it, or "not run, because ...">

SITES is every place that shares the cause, not only the one in the report:
one line each, a file and a function, no code. the steps after you read the
code for themselves. FEEDS is one line per command or caller, each of which a
test can reach.

RELATED is not fixed in this run. it goes to the person who started it.

ROOTED is `no, <what you could not find out>` when something the fix depends
on is still unknown, or the fix hangs on a decision only that person can
make. the run then waits for them instead of fixing a guess.
