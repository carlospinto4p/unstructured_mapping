# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Rules

1. **Self-Improvement**: When the user corrects a mistake, ALWAYS update the relevant guidelines (`.claude/rules/` or this file) to prevent it from happening again.

2. **Keep CLAUDE.md Minimal**: Do not include library schemas, architecture details, or information discoverable from the codebase. Keep only essential rules and commands here.

3. **Update CLAUDE.md Each Iteration**: Review and update this file when rules change or new important patterns emerge.

## Project Overview

Unstructured Mapping is a proof-of-concept library for mapping well-defined entities (as found in a knowledge graph database) to unstructured text. It detects entity mentions in free text, resolves them against a KG, and optionally updates the graph with newly discovered relationships.

## Shell Commands

Never use compound shell commands with `cd && git` or `cd &&` chaining. Always use separate commands or `cd` first, then run the git/shell command independently.

## Project Configuration

Store project rules and preferences in project config files (e.g., `.claude/settings.json`, `CLAUDE.md`), NOT in memory files. Never save user instructions as memory files.

## Versioning / Release

After version bumps, always stage and commit `uv.lock` along with the version change. Never forget the lock file.

## Testing

After any code change, run the full test suite and fix all failures before committing. Pay special attention to mock patching paths, fixture values, and assertion text that may need updating after refactors.

## Common Commands

**IMPORTANT**: Always use `uv run` to execute Python commands. Never run raw `python` commands.

```bash
# Install dependencies
uv sync --all-extras

# Run unit tests
uv run pytest tests/unit -v

# Run linter
uv run ruff check src/ tests/

# Run linter with auto-fix
uv run ruff check src/ tests/ --fix
```

## Code Style

- Line length: 78 characters (enforced by ruff)
- Type hints required
- **Do NOT use `from __future__ import annotations`** — the project requires Python >= 3.14, so all modern annotation features work natively
- Docstring style: Sphinx/reST (`:param:`, `:return:`, `:raises:`)
- In docstrings, use single backticks (`` `name` ``) not double (`` ``name`` ``)
