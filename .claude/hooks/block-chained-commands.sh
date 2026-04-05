#!/bin/bash
# Block compound shell commands (&&, ;) that involve git or cd.
# Hooks receive JSON on stdin with tool_input.command.
INPUT=$(cat)
echo "$INPUT" | python -c "
import sys, json
data = json.load(sys.stdin)
cmd = data.get('tool_input', {}).get('command', '')
if ('&&' in cmd or ';' in cmd) and ('git' in cmd or 'cd' in cmd):
    print('Blocked: no && or ; chaining with git/cd — use separate Bash calls', file=sys.stderr)
    sys.exit(2)
"
