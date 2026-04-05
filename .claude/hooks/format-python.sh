#!/bin/bash
# Auto-format Python files after Write/Edit.
# Hooks receive JSON on stdin with tool_input.file_path.
INPUT=$(cat)
FILE=$(echo "$INPUT" | python -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('tool_input', {}).get('file_path', ''))
")

if [[ "$FILE" == *.py ]]; then
    uv run ruff check --fix "$FILE"
    uv run ruff format "$FILE"
fi
