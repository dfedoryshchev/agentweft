#!/usr/bin/env bash
# crude. cat the flow into the cli and let it go.
set -e

NAME="${1:-summarise-and-check}"
DIR="flows/$NAME"

if [ ! -d "$DIR" ]; then
  echo "no such flow: $NAME"
  exit 1
fi

claude -p "$(cat $DIR/prompt.md)

$(cat $DIR/instructions.md)"
