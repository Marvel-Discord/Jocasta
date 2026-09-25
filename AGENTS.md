# AGENTS.md

## Code style

- snake_case for functions, variables, and parameters
- No repo-wide rename sweeps. When modifying a function that still carries a legacy concatenated name (e.g. `fetchpollmsg`, `keywordsearch`, `sortpolls`, `canview`), rename it to snake_case in the same change
- Preserve Discord-facing UX exactly unless told otherwise — command names, option names, and reply text come from decorators and strings, not function names; never rename those

## Testing

From the repo root (this directory), Python 3.14 venv at `.venv`:

```pwsh
$env:HOMESERVER="1"; $env:NEWSPINGROLE="1"; $env:SPOILER_THREAD_CHANNEL="1"; $env:REQUEST_SPOILER_THREAD_CHANNEL="1"; .\.venv\Scripts\python.exe -m pytest tests/ -v
```

- The env vars are required: tests import `config`, which reads them at import time, and there is no `.env` in the repo
- Note the spelling: `NEWSPINGROLE` (P-I-N-G)

## Git

- Commit subjects: lowercase imperative (e.g. `migrate single reads from postgres to api`)
- Work happens as stacked feature branches managed with `gh-stack` (one PR per layer, each based on the layer below); never merge mid-stack PRs with `gh pr merge` — use `gh stack merge`
- Layer plans live in `docs/plans/` at the workspace root (one level above this repo)
