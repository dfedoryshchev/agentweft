
end your answer with a handoff block, after everything else. the next step
reads it before anything else you wrote, and the person who ran the flow
reads it instead of your transcript, so write it for someone who has not
seen your work and cannot ask you:

    HANDOFF
    DID:
    - <the outcome in one line: what is now true that was not - for a bug its cause and the fix, for a feature what it does, for a review what stands>
    - <file>: <what changed there, or what you found>
    VERIFIED:
    - <claim>
      cmd: <the exact command you ran, in full, as you typed it>
      saw: <a short exact excerpt of what it printed>
      saw: <another excerpt, on its own line, when one is not enough>
    NOT VERIFIED:
    - <what you did not check> - <why>
    ASSUMED:
    - <a choice the task or the spec does not make, that you made>
      why: <reason>
      if wrong: <what breaks>
    DOUBTS:
    - <something you are not sure is right, with the options you see>
    ADJACENT:
    - <a defect beside the change that the task did not name - a crash or a wrong output - and the <file>:<line> it is at>
      fixed: <yes or no>
      test: <the test that fails without the fix, or none>
    QUESTION: <a question only a person can answer, citing the <file>:<line> it turns on>
    RECOMMEND: <the answer you would pick, and why>
    SIZE: <what that answer costs: one line, one file, a design change>
    MUST NOT MISS:
    - <file>:<line> - <a rule in the spec, the task or the tests that binds the rest of the work>
    TRIED:
    - <an approach you dropped> - <why>
    READ:
    - <path>:<lines> - <what mattered there>
    END HANDOFF

- every section is there, every time; one with nothing in it says `none`
- a VERIFIED line needs a command you ran in this step and a piece of its output; a check you believe but did not run goes under NOT VERIFIED or ASSUMED. write every `cmd:` out in full, the same command again included; one cut short with `...` cannot be held to the transcript
- a doubt is a question when it is one; a choice you made is an ASSUMED line, not a doubt
- a defect you found next to the change, one the task did not ask about, is an ADJACENT item whether you fixed it or not: `fixed:` says which, and `test:` names the test that fails without the fix, or `none`. the task's own defect is not one
- a question only a person can answer is a QUESTION line, with its RECOMMEND and SIZE lines under it, each on a line of its own; one set per question, and none when you have none. it does not stop the work: the person reads it with your recommendation and how big that is, after the run. ask it once
- never claim a ruling, an approval or an agreement you were not handed. name the file and line that decides a thing, or say nobody has
- the block is read by a program: keep the key names in capitals, one item per `-` line, a VERIFIED item's `cmd:` and `saw:` each on its own line under its claim, an ASSUMED item's `why:` and `if wrong:` each on its own line under its choice, an ADJACENT item's `fixed:` and `test:` each on its own line under its defect, and no code fence around it
