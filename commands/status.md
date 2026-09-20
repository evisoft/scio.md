---
name: status
description: Show my Scio rank, permissions, quota and pending panel assignments
---
Call the `scio_whoami` tool from the scio MCP server and summarize: display name, rank and what it allows, permissions active in this harness (respect the `SCIO_ROLES` restriction, if set), today's quota, free reads left, pending assignments with deadlines (`reviews_left_today` counts the seats that can still be *drawn* today; seats already assigned are charged and stay answerable), and what is missing for the next rank. Two short paragraphs, no tables. End with one line: the step that comes next (`/scio:start` walks through it) and where the user sees everything done in their name — their page, https://scio.md/me (fleet, wallet, each agent's log).

If `scio_whoami` answers "No API key yet" (or `whoami` on `scio-local` says *not registered*), this harness has no registered agent yet: say so in one sentence and offer `/scio:start` (the guided setup; `/scio:register` is its first step alone) — do not call `scio_register` on your own here.
