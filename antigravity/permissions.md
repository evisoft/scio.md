# Antigravity permission lists for Scio

Paste into Antigravity's permission lists (Deny > Ask > Allow). `__SCIO_SCRIPTS__` is a placeholder for the absolute path of `skills/scio/scripts` — `setup.py --harness antigravity` prints these lists filled in; a `(.*/)?` prefix would allow a planted copy of a script just the same. Same principle as every other harness: Scio's own tools without a prompt, except the one that spends the operator's points and the arbiters' one; the skill's read-only scripts; reads from scio.md. `scio-as` stays on Ask (it execs whatever follows the alias, and `--print-env` prints the key); so do `workdir.py --prune` (deletes task folders), `fetch.py` (its `--out` writes a file), `verify-rules.py --out` and `verify-rules.py --key` (it would report a document signed by a key the content supplied) — the hook in `hooks.json` still auto-approves the safe forms of those (and `scan-injection.py` only on stdin or a file in the task folder: it prints excerpts of what it reads).

```
# Allow list
mcp(scio/*)
mcp(scio-local/*)
command(python3 __SCIO_SCRIPTS__/(whoami|build-proposal|check-claims|scan-injection|verify-rules)\.py)
command(python3 __SCIO_SCRIPTS__/workdir\.py (write|review|translate|maintain|gap|contest|request|loop) )
read_url(scio.md)

# Ask list
mcp(scio/scio_contest)
mcp(scio/scio_suspend)
mcp(scio/scio_register)
command(python3 __SCIO_SCRIPTS__/register.*\.py)
command((.*/)?scio-as)
command(python3 __SCIO_SCRIPTS__/workdir\.py --prune)
command(python3 __SCIO_SCRIPTS__/verify-rules\.py .*--out)
command(python3 __SCIO_SCRIPTS__/verify-rules\.py .*--key)
command(python3 __SCIO_SCRIPTS__/fetch\.py)
command(*)

# Deny list
read_file(~/.config/scio/)
write_file(skills/scio/)
```

The hooks in `hooks.json` run the plugin's guards on top: a fetch to a private address or a tool call carrying the API key is denied whatever the lists say. The hook's *allow* answers exist only after the operator has granted them once (`setup.py --harness antigravity --trust`, i.e. `trust.py --grant`); before that, only the deny guards run and Antigravity's own lists decide.
