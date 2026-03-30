# Shell command guidelines

- Keep commands simple: one command per Bash call
  (no `&&`, `||`, or `;` chains).
- No `cd` prefix — already in project root.
- Always use `uv run` — never raw `python` or `pytest`.
- Unix-style: use `/dev/null` not `NUL` (MSYS bash on Windows).
- Git commands: plain git with simple `-m "..."` quoting.
