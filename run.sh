#!/usr/bin/env bash
# crude. cat the flow into the cli and let it go.
set -e

FLOW="flows/summarise-and-check.md"

claude -p "$(cat $FLOW)"
