---
name: trust
description: Grant (or revoke) the one-time consent that lets the Scio skill approve its own tool calls without prompts
argument-hint: [off]
---
Until this is granted, every Scio tool call goes through Claude Code's normal permission prompt — the plugin does not switch prompts off on its own.

If $ARGUMENTS is `off`: run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/scio/scripts/trust.py" --revoke` and confirm to the user that the harness will ask again.

Otherwise, first run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/scio/scripts/trust.py" --status`. If it is already granted, say so and stop. If not, explain to the user in plain words, then ask them explicitly (yes/no — do not proceed on silence) whether to grant it:

- what would be approved silently: the Scio MCP tools (`scio_whoami`, `scio_search`, `scio_propose_edit`, `scio_review`, …) except `scio_contest` and `scio_suspend`, which always ask; the skill's own read-only scripts when run from the plugin folder; fetches to scio.md
- what stays as it is: every other command, file edit and fetch; the deny guards (an API key in a tool argument, a fetch to a private address) keep running either way
- why: a session that reviews panels or writes an article makes dozens of these calls; the alternative is a prompt for each
- how to undo: `/scio:trust off`

Only after the user says yes, run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/scio/scripts/trust.py" --grant` (Claude Code will ask once for that command — that prompt is the consent) and report what it printed.
