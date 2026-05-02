#!/usr/bin/env python3
"""Pre-commit hook: fail if .claude/ has unstaged working-tree changes."""

import subprocess
import sys

result = subprocess.run(
    ["git", "diff", "--name-only", "--", ".claude/"],
    capture_output=True,
    text=True,
)
unstaged = result.stdout.strip()
if unstaged:
    print(
        "ERROR: Unstaged .claude/ changes will be missing from this commit:"
    )
    for path in unstaged.splitlines():
        print(f"  {path}")
    print("Stage them (git add) or stash before committing.")
    sys.exit(1)
