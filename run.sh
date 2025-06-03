#!/usr/bin/env bash
# crude. cat the flow into the cli and let it go.
set -e

NAME="${1:-summarise-and-check}"
DIR="flows/$NAME"

if [ ! -d "$DIR" ]; then
  echo "no such flow: $NAME"
  exit 1
fi

OUT=$(claude -p "$(cat $DIR/prompt.md)

$(cat $DIR/instructions.md)")

# the digest comes back as three lists now, put a rule between them so the
# "needs me" one is easy to find
if [ "$NAME" = "weekly-digest" ]; then
  echo "$OUT" | sed 's/^## /----/'
else
  echo "$OUT"
fi
