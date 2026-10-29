
end your answer with a handoff block, after everything else. the next step
reads it before anything else you wrote, and the person who ran the flow
reads it instead of your transcript, so write it for someone who has not
seen your work and cannot ask you:

    HANDOFF
    DID:
    - <the outcome in one line: what is now true that was not - for a bug its cause and the fix, for a feature what it does, for a review what stands>
    - <file>: <what changed there, or what you found>
    BECAUSE:
    - <a reason that shaped what you did: a spec line, a test, a code fact, a cost or a risk you weighed>
      from: <file>:<line>, a <test id>, a <gate>, or own read
      led to: a <test id>, a <file>:<lines> you changed, TRIED <the item>, ASSUMED <the item>, QUESTION, DECIDED <the ruling>, or nothing
    VERIFIED:
    - <claim>
      cmd: <the exact command you ran, in full, as you typed it; for a read or search tool call: Read <file>, Grep "<pattern>" <path>, Glob "<pattern>" <path>>
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
- a VERIFIED line needs a command you ran in this step, or a Read, Grep or Glob call you made in it, and a piece of its output; a check you believe but did not run goes under NOT VERIFIED or ASSUMED. write every `cmd:` out in full; one cut short with `...` cannot be held to the transcript. a claim shown by the same call as the VERIFIED item above it writes `cmd: same command as above`, those words and no others: the runner reads them as the nearest `cmd:` above that is written out, and any other short form names nothing it can find
- run a check as a call of its own, not at the end of a call that writes or edits a file, and cite that call. a `cmd:` that puts a stand-in such as `(test body)` or `(three new tests)` where part of the call was is a cut like `...`: neither can be held to the transcript
- a `saw:` is text the call printed, copied as it printed it, never a description of it such as `(empty output)` or `(no diff output)`. a check whose answer is that nothing prints makes the call print one: `git diff --quiet -- <file>; echo $?` prints `0` where `git diff` would print nothing
- BECAUSE holds the reasons that shaped the work, three to eight, one line each, never a trail of thought. `led to:` names one thing in this block or in the tree: a test id, the lines you changed, the TRIED, ASSUMED or QUESTION item it led to, or a DECIDED ruling; `nothing` is the honest answer for a reason that changed nothing, and a reason that came from no file, test or gate is `own read`
- a doubt is a question when it is one; a choice you made is an ASSUMED line, not a doubt
- a defect you found next to the change, one the task did not ask about, is an ADJACENT item whether you fixed it or not: `fixed:` says which, and `test:` names the test that fails without the fix, or `none`. the task's own defect is not one
- a question only a person can answer is a QUESTION line, with its RECOMMEND and SIZE lines under it, each on a line of its own; one set per question, and none when you have none. it does not stop the work: the person reads it with your recommendation and how big that is, after the run. ask it once
- never claim a ruling, an approval or an agreement you were not handed. name the file and line that decides a thing, or say nobody has
- the block is read by a program: keep the key names in capitals, one item per `-` line, a VERIFIED item's `cmd:` and `saw:` each on its own line under its claim, an ASSUMED item's `why:` and `if wrong:` each on its own line under its choice, an ADJACENT item's `fixed:` and `test:` each on its own line under its defect, a BECAUSE item's `from:` and `led to:` each on its own line under its reason, and no code fence around it
