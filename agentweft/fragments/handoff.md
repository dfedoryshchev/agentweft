
end your answer with a handoff block, after everything else. the next step
reads it before anything else you wrote, and the person who ran the flow
reads it instead of your transcript, so write it for someone who has not
seen your work and cannot ask you:

    HANDOFF
    DID:
    - <the outcome in one line: what is now true that was not - for a bug its cause and the fix, for a feature what it does, for a review what stands>
    - <file>: <what changed there, or what you found>
    VERIFIED:
    - <claim> | cmd: <the exact command you ran, as you typed it> | saw: <a short exact excerpt of what it printed>
    NOT VERIFIED:
    - <what you did not check> - <why>
    ASSUMED:
    - <a choice the task or the spec does not make, that you made> | why: <reason> | if wrong: <what breaks>
    DOUBTS:
    - <something you are not sure is right, or found and did not fix, with the options you see>
    MUST NOT MISS:
    - <file>:<line> - <a rule in the spec, the task or the tests that binds the rest of the work>
    TRIED:
    - <an approach you dropped> - <why>
    READ:
    - <path>:<lines> - <what mattered there>
    END HANDOFF

- every section is there, every time; one with nothing in it says `none`
- a VERIFIED line needs a command you ran in this step and a piece of its output; a check you believe but did not run goes under NOT VERIFIED or ASSUMED. the record is held against your transcript, and a claim it does not show is printed as such
- a doubt is a question when it is one; a choice you made is an ASSUMED line, not a doubt
- never claim a ruling, an approval or an agreement you were not handed. name the file and line that decides a thing, or say nobody has
- the block is read by a program: keep the key names in capitals and the `|` separators as shown, one item per `-` line, and no code fence around it
