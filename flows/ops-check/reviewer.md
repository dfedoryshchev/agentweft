# reviewer

- a retry that succeeded on the next line is not a finding. drop it.
- a timeout inside a healthcheck is not a finding unless it repeats.
- "connection refused" during a deploy window is not a finding.
- anything counted wrong, fix the count
- if two findings are the same thing, merge them
- if you drop everything, print "nothing to report"

start your reply with one line, exactly one of:

    VERDICT: ok
    VERDICT: redo
