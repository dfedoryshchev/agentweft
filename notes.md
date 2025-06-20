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
