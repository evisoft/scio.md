## What this changes

## Why (the situation that showed the need)

## Checklist
- [ ] `python3 tests/test-security.py` is green (new fixture added if a defence changed)
- [ ] `python3 scripts/gen-manifest.py` run last; `MANIFEST.sha256` and `PLUGIN.sha256` in this PR (`python3 scripts/gen-manifest.py --check` passes — no key, no network)
- [ ] The contract's copies (`tools.md`, `server/tools.json`, `tests/wiki/tools.json`) untouched, or all three regenerated with `scripts/sync-contract.py`
- [ ] No new network host, no new place that reads the keys file, no hand-written numbers
- [ ] `claude plugin validate .` passes
