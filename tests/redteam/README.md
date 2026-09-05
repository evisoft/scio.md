# Red-team fixtures

Attack payloads the skill must recognise, named after the attack class of `references/security.md` they exercise (not every class has a fixture yet: §2.5, §2.6, §2.8, §2.10 and §2.11 are policy defences, not text patterns). `tests/test-security.py` runs every fixture through the scanner, the proposal pre-flight and the hook guards and fails when a defence stops catching what it caught before. Add a fixture whenever a new attack is found in the wild — the fixture is the regression test.

`*.txt` — text scanned by `scan-injection.py` (expected: findings). `*.proposal.json` — `scio_propose_edit` inputs for `check-claims.py` (expected: blocked). `*.hook.json` — hook payloads for `guard-secrets.py` / `guard-fetch.py` (expected: denied). `clean.*` — benign counterparts (expected: pass).

The regression suites also consume focused JSON fixtures: `13-nonobject-proposal.json`
tests proposal-file loading; `14-invalid-claim-types.json` supplies malformed claim
fields; `15-shell-credential-paths.json` supplies credential-path spellings next to
shell operators. The last fixture is inspected as tool arguments, never executed.
