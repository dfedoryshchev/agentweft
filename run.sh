#!/usr/bin/env bash
# crude. cat the flow into the cli and let it go.
set -e

FLOW="flows/${1:-summarise-and-check}.md"

if [ ! -f "$FLOW" ]; then
  echo "no such flow: $FLOW"
  exit 1
fi

claude -p "$(cat $FLOW)"
