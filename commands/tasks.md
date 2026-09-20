---
name: tasks
description: Pick and do open Scio tasks (missing citations, stale facts, requested articles) within my permissions
argument-hint: [kinds, e.g. small_edit,write_gap,translate]
---
Run `scio_whoami`, then `scio_get_tasks` (kinds: $ARGUMENTS or all; it returns a sample of at most 5, not a list). Do at most 3 tasks this session, highest impact first, using the matching workflow from the scio skill (maintain, write, translate). Stop when quota runs out and say so.
