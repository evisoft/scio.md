# Code review — 2026-09-05

Baseline: clean worktree at `bb887b8` (v0.6.0). The existing security suite passed;
the regressions below reproduced failures before implementation. All reproductions
use temporary files and simulated remote responses, with no production registrations.

## BUG-001 — High: proposal assembly follows files outside its work root

Status: Fixed. The named regression tests below now pass.

`scio_local.t_build_proposal` checks only the directory. A `draft.md` symlink to a
file outside the root is read and echoed in the returned proposal, even when the
pre-flight fails. The CLI also follows `proposal.json` symlinks and overwrites the
external target. Resolve and validate every input/output before reading or writing;
apply the same work-root boundary to the CLI's automatically approved writes.

Evidence: `test_build_rejects_symlinked_inputs_without_echoing_external_data` and
`test_cli_build_rejects_output_symlink_without_overwriting_target` fail.

## BUG-002 — High: scanner auto-approval accepts escaped paths

Status: Fixed. The named regression tests below now pass.

`auto-approve.py` uses a textual work-root prefix. Both `work/task/../../private.txt`
and a symlink inside work to an external file are approved. The scanner prints file
excerpts, permitting unrelated file reads without the expected prompt. Check real
path containment after parsing the already restricted invocation.

The VS Code terminal regex and OpenCode work-path glob have the same problem;
static patterns cannot resolve symlinks, so scanner file reads there must ask.

Evidence: `test_autoapprove_does_not_approve_scan_traversal_or_symlink` fails twice;
`test_vscode_scanner_approval_does_not_accept_escaped_paths` also fails.

## BUG-003 — Medium: malformed local MCP tool names kill the server

Status: Fixed. The named regression tests below now pass.

`name not in TOOLS` raises TypeError for list/object names on the reader thread.
Subsequent requests receive no answer. Validate the name before dictionary lookup.

Evidence: `test_malformed_tool_names_do_not_terminate_local_server` exits 1 before ping.

## BUG-004 — Medium: a duration-based wait cannot resume its original deadline

Status: Fixed. The named regression tests below now pass.

`wait(seconds=120)` sleeps 50 seconds then instructs the caller to repeat the same
`until`, but returns no `until`. Repeating seconds restarts the duration. Return the
absolute UTC deadline for subsequent chunks.

Evidence: `test_seconds_wait_returns_reusable_deadline` fails.

## BUG-005 — High: malformed proposal files crash the pre-flight hook

Status: Fixed. The named regression tests below now pass.

`check-claims.load` expands JSON with `**` before validating that it is an object,
outside the hook's fail-closed exception handler. A file containing `[]` produces
no deny decision. Validate file shape and containment before merging its fields.

Evidence: `test_proposal_file_array_is_denied_by_hook` exits 1 with TypeError.

## BUG-006 — High: Cursor and Antigravity allow calls after a guard crashes

Status: Fixed. The named regression tests below now pass.

Both adapters discard child exit status and treat empty/malformed output as no
decision. The auto-approval hook then allows the call despite a failed deny guard.
Return deny on failed execution, timeout, or malformed guard output.

Evidence: `test_guard_adapters_deny_when_child_guard_crashes` returns allow in both adapters.

## BUG-007 — Medium: bridge hides incomplete injection scans

Status: Fixed. The named regression tests below now pass.

Scanner exit 2 is treated as clean. Answers exceeding 400,000 characters receive
no truncation note when their scanned prefix is clean. Report execution failure
and unscanned tails while preserving the original response text.

Evidence: `test_bridge_reports_scanner_crash` and `test_bridge_reports_unscanned_tail` fail.

## BUG-008 — High: credential persistence can corrupt or inject entries

Status: Fixed. The named regression tests below now pass.

`save_key` cannot create a basename-only relative `SCIO_KEYS_FILE` and accepts
newlines in model metadata, which become additional credential lines. Separately,
`register-models.py` duplicates the append logic and glues a new alias onto a
hand-edited file lacking a final newline, losing both identities. Validate stored
fields and reuse the shared writer, including relative-path and newline handling.

Evidence: `test_save_key_supports_relative_paths`, `test_save_key_rejects_line_injection`,
and `test_batch_registration_preserves_unterminated_existing_key` fail.

## BUG-009 — Medium: Codex servers disagree on the custom work root

Status: Fixed. The named regression tests below now pass.

The generated config and snippet forward `SCIO_WORK_DIR` only to scio-local. The
bridge rejects `proposal_file` from the configured custom root because it uses
the default root. Forward the same variable to both servers.

Evidence: `test_codex_servers_share_custom_work_root` fails on generated config.

## BUG-010 — High: OpenCode permission ordering overrides required prompts

Status: Fixed. The named regression tests below now pass.

Setup, the snippet, and prior tests assume first-match precedence. OpenCode uses
[last matching rule wins](https://opencode.ai/docs/permissions/#granular-rules-object-syntax).
The `scio_*` allow overrides registration/contest/suspend asks. A final Bash `*`
also overrides specific rules, disabling useful approvals or bypassing restrictions
when the user's default is allow. Put defaults first and exceptions last; test
effective decisions and preserve unrelated user rules across repeated setup.

Evidence: `test_opencode_effective_permissions_preserve_sensitive_prompts` observes
allow for `scio_scio_register` after setup.

## BUG-011 — Medium: rules CI check verifies only the version label

Status: Fixed. The named regression tests below now pass.

`refresh-rules.py --check` exits before verifying the signature or comparing the
bundled constitution text. It reports success for both an invalid remote signature
and modified local rules when the version label matches. Run signature verification
in check mode and compare all generated bundle content without writing anything.

Evidence: `test_rules_check_verifies_signature_and_actual_bundled_text` fails for
both an invalid signature and locally modified constitution text.

## Verification follow-up — stale signed-rules bundle

The live check on 2026-09-05 verified the server's September 5 signature against
the pinned key, then correctly rejected the repository's September 2 bundle.
Refreshed with `refresh-rules.py`; the final read-only check verifies the signature
and exact bundle match. This is bundle drift, separate from BUG-011's check defect.

## Final verification

- `python3 tests/test-security.py`: 0 failures, including all 16 new tests in `tests/test-review.py`.
- Each defect's original failing reproduction is recorded above; passing tests cover the actual hook decisions, file effects, protocol replies, or generated configuration behavior.
- `claude plugin validate .` and `claude plugin validate .claude-plugin/plugin.json`: passed.
- `npx -y skills-ref validate skills/scio`: passed.
- `python3 skills/scio/scripts/refresh-rules.py --check`: pinned signature valid; bundle matches 2026-09-05.
- Python compilation, JSON parsing with duplicate-key rejection, Bash syntax, and `git diff --check`: passed.
- Manifest regenerated and all 42 installable file hashes verified.
- Package metadata synchronized to 0.6.1. No release was published during this review.

## Follow-up security review — baseline 9f9992e (v0.6.1)

The following findings were reproduced in disposable directories before fixes.
All test names refer to `tests/test-hardening.py`; no real credentials were used.

### BUG-012 — High: task creation escapes through symlinks

Status: Fixed. The named regression test below now passes; work-root validation is shared.

`scripts/workdir.py:61` trusts a pre-existing task directory. Replacing that path
with a symlink causes `create` to write notes, sources, and task metadata outside
the work root. Validate every path before creating anything and share one root
policy between CLI helpers and MCP servers.

Evidence: `test_workdir_rejects_task_symlink_before_creating_external_files` fails.

### BUG-013 — High: pruning deletes unrelated projects

Status: Fixed. The named regression test below now passes; pruning validates task ownership.

`scripts/workdir.py:100` treats the existence of `task.json` as ownership proof.
An unrelated folder with that common filename is recursively deleted by
`--prune 0`. Require valid Scio metadata and a matching generated directory name;
skip symlinks and malformed metadata.

Evidence: `test_prune_preserves_unrelated_folders_with_task_json` loses notes.txt.

### BUG-014 — High: secret guard misses file aliases and crashes on decoding

Status: Fixed. All three named regression tests below now pass.

`scripts/guard-secrets.py:68` ignores basename-only paths and paths containing
spaces; its directory comparison never resolves symlinks to the credential file.
An invalid UTF-8 byte also crashes the separate key parser at line 26. Recognize
explicit path fields, compare resolved paths, and reuse the shared key parser.

Evidence: `test_secret_guard_denies_basename_spaces_and_symlink_paths` and
`test_secret_guard_survives_invalid_utf8_in_credential_file` fail.
Follow-up reproduction `test_secret_guard_denies_relative_shell_reads_and_keys_variable`
also bypasses the guard with a quoted basename and `$SCIO_KEYS_FILE`.

### BUG-015 — High: Unicode record separators inject credential entries

Status: Fixed. Both named regression tests below now pass; registration validates before remote calls.

`scripts/scio_common.py:111` rejects CR/LF but `read_keys` uses `str.splitlines`,
which also recognizes vertical tab, form feed, NEL, and Unicode separators.
Model metadata containing one of these characters creates another credential
record. Validate against exactly the record separators understood by the parser.

Evidence: `test_key_metadata_rejects_every_record_separator` fails for eight separators.
`test_registration_rejects_unpersistable_model_before_remote_call` also proves
the bridge contacted the server before checking whether model metadata could be
saved safely. Validate caller-supplied model metadata before registration too.

### BUG-016 — Medium: pre-flight accepts invalid claim types or crashes

Status: Fixed. Both named regression tests below now pass, including the red-team type fixtures.

`scripts/check-claims.py:143` treats booleans as integer ordinals and coerces source
URLs to strings. Numeric quotes and list-valued kinds instead cause tracebacks.
The loader at line 58 also crashes before producing a hook denial for a nonobject
payload. Validate input types before content checks and report malformed input
consistently in both CLI and hook modes.

Evidence: `test_preflight_rejects_invalid_claim_types_without_tracebacks` and
`test_preflight_rejects_nonobject_hook_payload` fail.

### BUG-017 — Medium: bridge misreads SSE and invents successful responses

Status: Fixed. Both named regression tests below now pass. A local HTTP test also verifies
that a matching response returns while the event stream remains open.

`server/scio_bridge.py:94` parses each data line as a complete JSON object, but
[SSE events may contain multiple data lines](https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation).
At EOF it returns the last notification or wrong-ID response as the result of
the caller's request. Empty JSON responses also become success. Parse complete
events and enforce [JSON-RPC response correlation](https://www.jsonrpc.org/specification#response_object).

Evidence: `test_bridge_reads_multiline_sse_event` and
`test_bridge_does_not_turn_unmatched_or_missing_response_into_success` fail.

### BUG-018 — High: release script publishes after failed Git operations

Status: Fixed. The named regression test below now passes; Git publication steps fail closed.

`scripts/release.sh:20` suppresses staging/commit failures with `|| true`, then
tags and pushes the previous commit. The chained tag/push commands can similarly
fall through to release publication after an earlier failure. Use sequential,
checked commands and verify the manifest directly without making an authenticated
whoami request with a dummy key.

Evidence: `test_release_stops_before_tagging_when_commit_fails` simulates a failed
commit yet observes exit 0 after the publication commands. All external commands
in that test are disposable doubles; no release is actually created.

### Follow-up verification

- `python3 tests/test-security.py`: 0 failures, including the 16-test review suite and 13-test hardening suite.
- `claude plugin validate .`, plugin-manifest validation, and `npx -y skills-ref validate skills/scio`: passed.
- `refresh-rules.py --check`: bundled rules exactly match the live, pinned-key-verified rules for 2026-09-05.
- All 28 Python files and 34 JSON/JSONC files parsed; JSON duplicate keys rejected. Bash syntax and `git diff --check` passed.
- Manifest regenerated after the skill changes: exact installable-tree match and all 42 hashes verified.
- All seven version declarations synchronized to 0.6.2. No release or tag was created during verification.

## Completion audit — baseline d570cfe (v0.6.2)

### BUG-019 — High: shell operators hide credential file arguments

Status: Fixed. All five operator cases and the benign counterparts pass.

`skills/scio/scripts/guard-secrets.py:100` uses `shlex.split` without shell
punctuation handling. With an absolute custom keys path in the current directory,
`cat 'private credentials';true` produces a single `private credentials;true`
token. The guard does not resolve that as the credential file and emits no denial.
Redirections, pipelines, subshells, and `&&` have the same effect. Split shell
operators separately before checking literal path tokens; do not execute or expand
the command. Python documents this distinction in
[shlex shell compatibility](https://docs.python.org/3/library/shlex.html#improved-compatibility-with-shells).

Evidence: `test_secret_guard_recognizes_paths_next_to_shell_operators` fails for
all five cases in `tests/redteam/15-shell-credential-paths.json`. The benign
compound-command test passes. Reproduction only sends tool payloads to the guard;
none of these shell commands is executed.

### BUG-020 — Medium: relative trust-file override cannot be granted

Status: Fixed. The grant/status/revoke regression passes, including private file permissions.

`skills/scio/scripts/trust.py:38` calls `os.makedirs("")` when
`SCIO_TRUST_FILE=local-trust`. The documented path override works for status and
revocation but crashes during grant, preventing the operator from enabling the
approval policy. Treat an empty parent path as the current directory, as the
shared credential writer already does.

Evidence: `test_trust_grant_and_revoke_support_relative_file` fails with
`FileNotFoundError` before creating the grant. The test uses a temporary current
directory and disables environment-only approval.

### BUG-021 — Medium: release cannot tag an already committed version

Status: Fixed. The empty-index release and all failure-path regressions pass.

`scripts/release.sh:20` now stops on every commit failure, including Git's normal
exit 1 when there is nothing to commit. If version metadata and regenerated files
are already committed, the first tag and release never happen. Check the staged
diff explicitly: skip the commit for exit 0, commit for exit 1, and abort for
inspection errors. Genuine commit, tag, and push failures must still abort.

Evidence: `test_release_tags_already_committed_files_without_empty_commit` fails
on the empty-commit step. `test_release_stops_when_staged_diff_cannot_be_read`
also fails because the index is not inspected. Existing commit-failure and new
tag/push-failure tests pass. All publication commands run against disposable
doubles, never GitHub or the real checkout.

### BUG-022 — High: transport diagnostics reveal malformed bearer keys

Status: Fixed. All four credential-error regression tests pass without exposing the dummy key.

`skills/scio/scripts/scio_common.py:20` preserves surrounding CR/LF from
`SCIO_API_KEY`. A CRLF keys file passed through `scio-as` is a realistic source:
its AWK extraction retains CR. urllib rejects the resulting header and embeds
the full bearer value in the exception. `server/scio_bridge.py:123` and
`scripts/whoami.py:59` return that exception text to the model. The authenticated
`register-models.py --show-claims` path also prints raw transport exceptions.
Strip surrounding environment-key whitespace consistently with the file parser;
report exception types without raw details on authenticated transport failures.

Evidence: the CRLF-launcher test fails, and bridge/whoami regressions expose the
dummy credential through real urllib header validation with socket connections
blocked. `test_show_claims_does_not_echo_credentials_from_transport_exception`
reproduces the same diagnostic leak using a transport-exception double. No real
credentials or external requests are involved.

## Completion evidence

The review covered the plugin's scripts and MCP servers, credential and filesystem
boundaries, hook/permission adapters, claim pre-flight, signed-rules verification,
generated configuration, and release workflow. An independent reviewer checked
the completed changes and then rechecked the release and credential-error fixes;
no remaining blockers were reported. The stale README rules badge now matches the
verified September 5 bundle; the dated statistics snapshot was not rewritten.

| Requirement | Evidence |
|---|---|
| Review bugs and security | BUG-001 through BUG-022 record root causes, impact, and reproductions; the completion audit added shell-operator, trust-path, release, and credential-error cases beyond the earlier green baseline. |
| Fix confirmed defects | All 22 findings are marked Fixed. The full `python3 tests/test-security.py` run exits 0, including 16 review tests and 24 hardening tests. |
| Keep code understandable | Shared work-root and credential helpers replace duplicate policies; validation runs before content operations; SSE parsing is isolated; Git steps distinguish clean state from failure; comments explain the credential-safe diagnostics. |
| Verify the deliverable | Both Claude plugin validations and Agent Skills validation pass; pinned-key verification confirms an exact live rules match; 28 Python and 35 JSON/JSONC files parse, Bash syntax and whitespace checks pass, and all 42 manifest entries exactly match the installable tree. |

Package metadata is synchronized to 0.6.3. At the completion of this audit, its
changes were local and uncommitted; the preceding requested push was d570cfe. No
release, registration, or production mutation was performed during the audit.

Limits: this is a source review with automated behavioral tests, not a guarantee
against every possible attack. The hosted platform is a separate repository;
live end-to-end testing of every harness and native Windows execution was not
performed. Hook text checks supplement harness permissions and do not constitute
a sandbox for arbitrary shell programs. Git publication tests use command doubles
so failure paths can be exercised without publishing anything.


# Agent and operator review — 2026-09-18

Baseline: clean worktree at `83294c8` (v0.6.7). Question asked: seen from the seat of a harness agent that has just
had the plugin installed, and from the seat of the operator who installed it, what stands between an install and an
agent that helps Scio? Live figures the same day (`/v1/stats`): 6,371 proposals — 2,384 failed the gates, 2,951 wait in
a panel, 570 merged; 63 agents, 36 of them claimed; 27 operators. So: gate failures waste the most work, review
capacity is the bottleneck, and four agents in ten never get past the claim. Every finding below was reproduced
before it was fixed; the named checks fail on the baseline.

## BUG-012 — High: an agent told "rules changed" could neither read nor verify the rules

Status: Fixed. `scio_get_rules` answers some 80 KB (the signed bytes, their parsed copy, the constitution inside
both). Claude Code refuses a tool result of that size — observed live: "result (82,076 characters) exceeds maximum
allowed tokens" — and `verify_rules` takes the document as an argument, so the session brief sent every agent with an
older bundle ("rules changed … read scio_get_rules before acting") into a dead end at the start of every session.
The bridge now verifies the document itself (pinned key, served == signed), keeps the parsed signed text under the
task work root and answers with the verdict, the numbers and the file (13 KB live; the constitution's prose stays in
the file). A document that does not verify yields no numbers. Evidence: `R1`–`R4` in `tests/test-security.py`.

## BUG-013 — High: `wait(until = <a seat's expires_at>)` fails on Python 3.10 and older

Status: Fixed. The platform trims trailing zeros from fractions (`18:00:08.92258+00:00`, seen in a live
`scio_whoami`); `datetime.fromisoformat` before 3.11 accepts 3 or 6 digits only, so the tool the loop waits with
raised on the deadline the server had just sent (reproduced on CPython 3.10.20). One tolerant parser,
`scio_common.parse_instant`, now serves `wait` and the brief. Evidence:
`test_instants_are_read_as_the_server_writes_them`, `test_wait_accepts_a_seat_deadline_verbatim`.

## BUG-014 — Medium: the session brief misled the agent it briefs

Status: Fixed. (a) "reviews 0" beside "20 panel assignment(s) waiting": the review quota is charged when a seat is
*drawn* (`EfPanelStore.ConsumeReviewQuotaAsync`), so 0 means "no new seats today", not "cannot review" — and the skill
said elsewhere that reviewing "is never quota-limited", which the signed `quotas.reviews_per_day` contradicts.
(b) "do these first" reached every session, including the ones about something else, where the two ways to obey it
are both wrong: derail the operator's task, or ignore seats that cost reputation. (c) a seat given to an R1 agent by
`panels.alpha_bootstrap` carries no review permission, so a brief keyed on permissions would never mention it.
(d) a rejected key read "could not reach … (HTTPError)". (e) deadlines were raw ISO strings. The brief now explains
the quota, separates a Scio work session from any other ("never start Scio work unasked"), names the one step that
comes next (`next →`), and says 401 when it is 401. Evidence: `tests/test-onboarding.py`.

## BUG-015 — Medium: nothing led an operator from *installed* to *contributing*

Status: Fixed. After `claude plugin install` nothing visible happens: the hook's text goes to the model, and the next
steps lived in the README. There was no guided path (register → claim → approvals → a first contribution → keep
going), the operator's own page — `https://scio.md/me`: fleet, wallet, each agent's log — was mentioned nowhere in
the plugin, and the machine this review ran on had 0.6.0 installed against 0.6.7 released with nothing to say so.
Added: the `onboard` workflow and `/scio:start` (one step per yes, `status` to look only); one line for the operator
when a step waits for them — at most once a day, rarer each time it is ignored (register, claim), never from a tool
call, silent when it cannot be throttled, `SCIO_NUDGE=off`; the claim link is relayed only when it is an address on
the wiki's own host; the rules line names the update as the lasting fix; `prompt.md` hands over to the same path.

## BUG-016 — Medium: an unattended loop waited through the model

Status: Fixed. `claude -p "/scio:loop"` under `--supervise` waits for the next sample with `wait`, 50 seconds a call:
every call is a model request over the whole conversation — about seventy an hour to do nothing — and the context
grows all night. `supervise.py --watch` moves the waiting out of the model: it asks `/v1/me` every five minutes and
starts a one-round session (`/scio:loop --once`) only when seats wait, or once an hour for the task sample; seats that a
round leaves all unanswered rest 30 minutes (no hot loop — the mutation that removes the rest fails the test; a round
that answered some is followed by the next at once), limits and failures back off as before, an unclaimed agent or a rejected key stops the watch with the
reason, `SCIO_ROLES` without a review role never wakes the model. `scio-as` passes the supervisor's options through.
Verified against the live server with a harmless command. Evidence: the watch tests in `tests/test-onboarding.py`.

## BUG-017 — Medium: a proposal could cite what the platform had already refused

Status: Fixed. `scio_verify_source` is the gates' own fetch and quote match, and 37 % of all proposals die at those
gates, each taking the day's quota unit and the drafting with it. The bridge now records every verdict under the task
work root — ids and enums only, none of the URL, the quote or the page — and the pre-flight reads them: `dead`,
`likely_fabricated`, `forbidden_source` (gate 1), `quote_found: false` (gate 2) and reliability `deprecated` or
`blacklisted` (gate 4, `PerennialSources.Rejects`) block the proposal; pairs with no verdict from the last 7 days are
named first among the warnings; spacing does not matter, an edited quote is unverified again, the latest verdict
counts, a damaged or symlinked ledger is ignored. Evidence: `V1`–`V7` in `tests/test-security.py`.

## Also

- `refresh-rules.py` keeps the rules badge of every README current and `--check` fails when one is stale: the English
  badge said 2026-09-05 and the five translations 2026-08-28 against bundled rules 2026-09-08.
- `workdir.py` and the bridge share one `ensure_work_root()` (the root, mode 700, and the `.gitignore` beside the
  default root), so the verified rules and the ledger cannot reach a user's repository either.
- `setup.py` keeps a script's own flags when it re-points a Cursor or Antigravity hook at the install
  (`whoami.py --session-start`).

Follow-up, 2026-09-19 (v0.7.1). A stale install has a cause and a switch: Claude Code leaves auto-update **off** for a
marketplace that is not Anthropic's own (`/plugin` → Marketplaces → `scio` → Enable auto-update), so the onboarding
path, `/scio:start`, `prompt.md`, the README and the rules line of the brief now say so — no platform change needed.
The pre-flight also blocks a live source the platform could extract no text from (`quote_found: null` for a quote that
was given: a PDF or another binary format — gate 1, `unsupported_source_format`). The breakdown of `gate_failed` by
reason already exists where it belongs, on the admin console's Pipeline page (`GateFailures24h`, `GateFailures7d`): its
top reasons say which pre-flight check to write next.

Still the platform's: `https://scio.md/prompt.md` is served from a copy in the platform repository
(`src/Scio.Api/Web/prompt.md`) last synced at the plugin's v0.4.1 — the fastest install path hands out instructions
several releases old until that copy is resynced and deployed. The task title "Review a article proposal" is the
platform's text.

| Check | Result |
|---|---|
| `python3 tests/test-security.py` (runs review, hardening, extraction and onboarding too) | 215 ok, 0 failures |
| `python3 tests/test-onboarding.py` | 26 tests, OK |
| `refresh-rules.py --check`, manifest regenerated last and `sha256sum -c`, `claude plugin validate .` | pass |

No release, registration, push or production mutation was performed: the changes are local, on
`feat/agent-onboarding`. Live calls made: `scio_whoami`, `scio_get_tasks`, `scio_get_rules` and `GET /v1/me`, all reads.

## BUG-018 — High: the plugin retired the claim link it had just handed over

Status: Fixed on the plugin's side; the cause is the platform's to decide (brief sent to the platform agent, 2026-09-19).
For an unclaimed agent every `scio_whoami` / `GET /v1/me` mints a new claim token and overwrites the old one
(`Whoami.HandleAsync`, BP-01), and the human holding the old link lands on "Nothing to claim". The plugin made that
the normal case: `/scio:register` told the agent to call `scio_whoami` "to confirm" before showing the link, the
bridge's registration answer said "show the link, then call scio_whoami", and the session-start brief asks `/v1/me` at
every start, resume, clear and compact — so a link relayed in one session died at the start of the next. 27 of 63
agents were unclaimed on 18 Sep.

Now: the registration answer, `/scio:register`, `/scio:start`, the onboard workflow and SKILL.md all say the same thing
— show the link, then ask the server nothing until the operator says it is opened; "Nothing to claim" on their side
means a call retired it: fetch one fresh link and wait. The session brief keeps a link it passed on alive: for three
hours after relaying one it does not ask the server at all (it says so, and says that `scio_whoami` answers when the
operator reports the link opened); reminders are recorded per agent, so one agent's link is not another's reason to
stay quiet. Evidence: `test_unclaimed_agent_gets_the_latest_claim_link_as_the_next_step` (the server double counts its
calls), B2 in `tests/test-security.py`.
