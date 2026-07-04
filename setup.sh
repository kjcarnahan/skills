#!/usr/bin/env bash
# Convenience wrapper so setup works right after cloning the repo:
#   bash setup.sh
# The real script lives with the module in skills/yarbo-patrol/scripts/.
set -euo pipefail
exec bash "$(dirname "$0")/skills/yarbo-patrol/scripts/setup.sh" "$@"
