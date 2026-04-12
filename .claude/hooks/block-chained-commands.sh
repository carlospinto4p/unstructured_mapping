#!/bin/bash
# Block compound shell commands that involve git or cd.
# Hooks receive JSON on stdin with tool_input.command.
# Chaining covers &&, ;, and newline-separated commands
# (multi-line Bash calls arrive as one string with \n).
# Quoted regions (including heredoc commit messages) are
# stripped before the newline check so legitimate
# git commit -m "$(cat <<EOF ... EOF)" still passes.
INPUT=$(cat)
echo "$INPUT" | python -c "
import sys, json, re
data = json.load(sys.stdin)
cmd = data.get('tool_input', {}).get('command', '')
# Strip single/double quoted spans and heredoc bodies.
stripped = re.sub(r\"'[^']*'|\\\"[^\\\"]*\\\"\", '', cmd)
stripped = re.sub(r'<<-?\'?(\w+)\'?.*?^\1', '', stripped, flags=re.S|re.M)
chained = '&&' in stripped or ';' in stripped or '\n' in stripped.strip()
if chained and ('git ' in cmd or 'cd ' in cmd):
    print('Blocked: no &&, ;, or newline chaining with git/cd — use separate Bash calls', file=sys.stderr)
    sys.exit(2)
"
