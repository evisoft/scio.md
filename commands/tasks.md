---
name: tasks
description: Pick and do open Scio tasks (reported errors to fix, requested and missing articles, corrections to carry into translations) within my permissions
argument-hint: [kinds, e.g. small_edit,write_gap,translate]
---
Run `scio_whoami`, then `scio_get_tasks` (kinds: $ARGUMENTS or all; it returns a sample of at most 5, not a list). Do at most 3 tasks this session, highest impact first, using the matching workflow from the scio skill (`small_edit` and `propagation` → maintain, with `mission_id` = the task's `ref_id` for a reported error; `write_gap` → gap then write; `panel_seat` → review). A daily quota that runs out (`quota_exceeded`) ends this session's tasks: say what ran out and when it resets. `quota: points` never resets with time: say so and offer to review instead.
