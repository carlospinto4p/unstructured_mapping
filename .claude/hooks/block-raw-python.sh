#!/bin/bash
# Block raw python commands — must use "uv run" instead.
# Allows python inside .venv/ paths (e.g. pytest runner).
# Hooks receive JSON on stdin with tool_input.command.
python -c "
import sys, json, re
data = json.load(sys.stdin)
cmd = data.get('tool_input', {}).get('command', '')
# Allow: uv run python, .venv/Scripts/python, .venv/bin/python
# Block: bare python, python3, python -c, etc.
if re.search(r'(?<!\S)python[23]?\s', cmd):
    if 'uv run' not in cmd and '.venv' not in cmd:
        print(
            'Blocked: use \"uv run python\" instead of'
            ' raw \"python\"',
            file=sys.stderr,
        )
        sys.exit(2)
"
