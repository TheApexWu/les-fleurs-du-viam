#!/bin/sh
# The module ships its own copy of the shared core; run this after editing ../fleurs_core.py.
cp "$(dirname "$0")/../fleurs_core.py" "$(dirname "$0")/src/fleurs_core.py"
