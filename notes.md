# notes

## 2025-05-30

week one. two flows.

what worked
- the check step. it caught itself inventing a number in the summary, twice.
  splitting summarise and check into two passes is the whole trick i think.
- keeping the prompt in a file instead of in my shell history

what didnt
- the cli times out on the big folder and i lose the whole run
- i am pasting the same "output markdown, nothing else" line into every flow
- hardcoded paths everywhere, if i move the folder its all broken

## 2025-06-20

the chaining thing works better than i expected. the digest draft goes in as
plain text at the bottom of the critique prompt and it just picks it up. no
json, no structure, nothing clever.

things i keep hitting
- every flow wants the same three lines at the top about markdown only and no
  preamble. i am copying them by hand into every instructions.md
- when a step fails halfway i lose the first step too and have to rerun the lot
- runs/ is going to get big

## 2025-06-29

june retro. four flows, one runner, run.sh gone.

what sticks
- two passes beats one prompt, every single time. draft then critique.
- the shared header fragment. should have done it in week two.
- keeping the rules in a separate file from the prompt. i can change how it
  behaves without touching what it does.

what does not
- competitor-watch. i have narrowed it twice and it still tells me things i do
  not care about. i think the flow is wrong, not the prompt.
- naming. flows/, fragments/, runs/. i have renamed the flow folder three times
  and i will probably do it again.
- no idea which runs failed without opening them

## 2025-07-12

roles that argue produce better output. i did not expect that.

the reviewer is the same model with a different prompt, and it still catches
the worker inventing things, because it is not the one that wrote them. one
model doing summarise-then-check in a single pass defends its own text. two
passes with different instructions does not.

the planner matters less than i thought. mostly it stops the worker starting
in the middle.
