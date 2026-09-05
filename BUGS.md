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
