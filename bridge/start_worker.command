#!/bin/bash
# Double-click me in Finder: installs boto3 for the user's Python and starts the PALIMPSEST LLM bridge worker.
cd "$(dirname "$0")/.." || exit 1
echo "PALIMPSEST bridge worker — repo: $(pwd)"
PY=$(command -v python3)
echo "python: $PY ($($PY --version 2>&1))"
"$PY" -m pip install -q --user boto3 2>&1 | tail -2
if pgrep -f "bridge/worker.py" > /dev/null; then echo "worker already running"; else
  nohup "$PY" bridge/worker.py >> bridge/worker.log 2>&1 &
  echo "worker started (pid $!) — log: bridge/worker.log"
fi
sleep 3; tail -5 bridge/worker.log
echo; echo "You can close this window; the worker keeps running. To stop it: create bridge/requests/stop.json containing {\"op\":\"stop\"}"
