# flows

prompts and a runner for the things i want to happen without me sitting there.

## the flows

- summarise-and-check - read a folder, summarise it, then check its own summary
  against the source and delete what it cannot back up
- weekly-digest - what changed this week, what needs me, what can wait
- ops-check - read today's logs and only tell me what is wrong
- competitor-watch - what the other lot changed since last week

## running one

    ./run.sh weekly-digest

each flow is a folder now. prompt.md is what to do, instructions.md is the
rules it has to follow.
