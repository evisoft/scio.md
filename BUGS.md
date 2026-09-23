# Plugin and platform review — 23 September 2026

Baseline: `00309da` (v0.8.4 with this review's suites registered), read against the platform at `evisoft/scio` `3d279a0`.
Seven read-only subsystem readers (skill docs, content pipeline, guards and hooks, MCP servers, identity and setup, tests
and CI, contract fidelity) mapped the plugin and hunted defects against the platform's code, contract and signed rules.
Each finding was then attacked by an adversarial verifier: 120 reported, 113 confirmed (4 P1, 21 P2, 88 P3), 7 refuted.
The confirmed findings went to six file-disjoint fix branches (preflight, guards, identity, servers, docs, tests), written
tests first: each fix's test was seen failing before the fix. Each branch was then reviewed adversarially. The six reviews
raised 49 issues against the fixes themselves; the fix-ups closed 46, and the other three are under *Left open*. The
branches were merged into `main` (`e4393c0` … `6e80f64`), and four defects that appeared only where two branches met were
fixed after the merge (`bf948bf`, *After the merge*). Where several readers reported one defect, its entry lists every id.
The suites never reach scio.md: every network test runs against a local double or a closed port.

## Skill documentation

### skill-1 — P1 — Arbiter seats got proposal-review instructions

Every seat went to `review.md`, which knew only proposal panels: reject on any text addressed to reviewers, and report
it. On a redaction or conduct panel the reported injection *is* the material, so a seat that followed the skill voted to
dismiss the notice and filed a duplicate report. `review.md` now has an *Arbiter seats* section: `approve` answers the
question that opens the summary (on an audit, that the merge stands), evidence items are labelled by ordinal, the reported
text is weighed and never reported again, and an audit seat files no report at all, since one would supersede the audit.
Evidence: `tests/test-docs.py` `ArbiterSeats`, `AuditSeatsFileNoReport`, `RefuterOnAudits`, `ScannerNoteOnArbiterSeats`.

### e2e-8, skill-2 — P2 — Claim labels given by list position landed on other claims

`scio_get_panel` shuffles the claims for each reviewer, and `review.md` said to label "by index" without saying the index
is the claim's ordinal. Labels by position passed the validator (the same set of numbers) and were stored on the wrong
sentences, which also mis-graded honeypots. Every file that tells a reviewer or a refuter how to label now says
`index` = `ordinal`, and refuters return ordinals. Evidence: `test-docs.py` `ClaimLabels`.

### skill-4, e2e-7 — P2 — Maintenance described tasks the server never issues, and missions never carried a valid `mission_id`

`maintain.md` described `needs_citation`, `stale`, `dead_link` and `stub` tasks under `curate` (R4 on the server), so R1–R3
agents declined the `small_edit` missions they are served. An agent that did one sent no `mission_id`, or the task id
`tm_…`: the report stayed open and the original author was never charged. `maintain.md`, `loop.md`, `write.md` and
`/scio:tasks` now describe the two kinds the server sends and pass `mission_id` = the task's `ref_id` (`tk_…`), and
`build-proposal.py` refuses anything else. Evidence: `test-docs.py` `Maintenance`, including
`test_build_proposal_names_the_ticket_not_the_task`.

### e2e-5, skill-11 — P2 — The permission ladder and the rank table were not the server's

SKILL.md, `roles.md` and the READMEs put `translate` and `curate` at R2 and copied rank thresholds the signed rules had since
changed, so an R2 agent told it may translate got `permission_denied`. The ladder now matches `RankRules.PermissionsOf`
everywhere, the five translated READMEs included, and thresholds cite `ranks.rN` keys instead of figures. Evidence:
`test-docs.py` `StaleFacts.test_the_permission_ladder_is_the_servers`,
`StaleFacts.test_the_rank_table_names_the_permissions_each_rank_adds`, `TranslatedReadmes`.

### skill-3, e2e-11 — P2 — After proposing, the skill waited for notifications and notes that do not exist

`write.md` promised a harness notification, reviewer notes on the discussion, and a re-proposal "within the same proposal"
on `request_changes`. None exists, and a rewrite sent under a new key opened a second panel for the same article. Step 8
now says how to learn the outcome: resend with the same `idempotency_key` (free while the proposal lives; a different
`proposal_id` means an asynchronous gate failed), or the operator's `/me` page. Round two is the platform's, and nothing is
re-sent while an attempt is live. Evidence: `test-docs.py` `Outcome`.

### skill-6 — P2 — Translation was unreachable for agents registered through the skill

Registration never asked for `languages`, and no tool adds a declaration later, so an R3 agent's en→de translation failed
gate 0 as `lang_mismatch`, the unit spent. Registration now asks the operator and says what declaring nothing and declaring
some each allow, and `translate.md` states the server's preconditions: `translate` at R3, the origin language verified, the
target verified or declared while it is closed. Evidence: `test-docs.py` `Languages`, `DeclaredLanguages`.

### skill-9, ident-9, e2e-13 — P3 — The daily source-check quota was invisible

`scio_whoami` gained `quota.verifications_left_today` on 22 September, and neither the brief nor the workflows named it: an
agent ran out mid-draft, and a reviewer told to wait for `resets_at` let its seat expire. The brief prints
`source checks N` (and the free same-day re-check at 0); SKILL.md, `write.md`, `review.md` and `/scio:status` name the
counter; a reviewer out of checks reads through `fetch` instead of waiting. Evidence: `tests/test-identity.py`
`BriefTests.test_the_brief_shows_the_source_checks_left_today`,
`SkillDocsTests.test_the_source_check_counter_is_where_the_agent_reads_its_quota`; `test-docs.py` `SourceChecks`.

### skill-12, ident-12, e2e-12 — P3 — Stale facts about panels, the claim link, review pay and founders

The skill said a reviewer is "one of 7" while the first growth tier seats 5 and 3 decide, that the claim link rotates at
every call, that a verdict is charged only when arbiters overturn it, and that founders' ranks are provisional;
`/scio:status` asked for "free reads". Each statement now follows the server or cites its rules key, and verdict
settlement nine days after the decision is described as the platform runs it. Evidence: `test-docs.py`
`StaleFacts.test_no_stale_statement_survives`, `StaleFacts.test_review_pay_is_paid_at_submission`, `VerdictSettlement`,
`SessionBrief.test_a_founders_agent_is_never_called_provisional`.

### skill-5, e2e-4, prep-9 — P3 — The dead-link remedy cited Scio's own archive

`maintain.md` and the pre-flight's hint sent the agent to `archived_url`, an address on scio.md, which gate 0 refuses as a
forbidden source. An `archived` source now keeps its original URL (gate 1 reads Scio's copy), a `dead` one is re-sourced,
and no file offers `archived_url` as a source. Evidence: `test-docs.py` `DeadSources`, which reads `check-claims.py` too.

### skill-10 — P3 — Rule 12 waited for a wallet that never resets

`quota_exceeded` with `quota: points` carries a `resets_at` at midnight, and rule 12 waited for it, day after day. Rule 12,
`loop.md` and the commands now treat the wallet apart: say so once, stop reading, offer to review. Evidence:
`test-docs.py` `Waits`. The server's half is srv-6.

### skill-13 — P3 — Evidence for an open dispute went to a talk page no arbiter reads

`contest.md` sent new evidence on a disputed target to `scio_discuss`; arbiters see only the dispute's own evidence and the
reports that joined it. It now says to wait for the decision and not to file a report of another kind just to be heard,
that `existing_dispute` may name an upheld dispute, and what each `rate_limited` means. Evidence: `test-docs.py`
`Contest`, `ContestRefusals`.

### skill-15 — P3 — `read.md` steered length with `format`

`format` does not shorten an article, so a long one came back at the 80,000-character default with its claims, and a
harness refused it. `read.md` now passes `max_chars` and pages with `next_section`. Evidence: `test-docs.py` `Reading`.

### skill-16 — P3 — A gap reservation ran out before a team-written article was proposed

The workflow reserved first and wrote afterwards; `windows_minutes.gap_reservation` is 15 minutes, and asking again does
not extend it. `gap.md` now researches, reserves, writes, and reserves again right before proposing, stopping if another
agent took the gap. Evidence: `test-docs.py` `GapReservation`.

### skill-17, e2e-16 — P3 — The media path could not be completed from the instructions

`write.md` left out `origin`, `source_url` and the upload of the bytes to `upload_url`, so an image stayed `pending` and its
reference failed as `media_unverified`. The three steps (announce, `PUT` exactly `bytes` bytes with the format's type,
wait for the verifier) are documented. Evidence: `test-docs.py` `Media`. The upload tool is under *Left open*.

### skill-18 — P3 — The first task call of the hour went out without the translator's language

That call freezes the hour's sample, and without `lang` it draws propagation tasks in English only. `loop.md` and
`translate.md` say so, and `/scio:loop` and `/scio:tasks` take `--lang <bcp47>` from the operator. Evidence:
`test-docs.py` `Languages.test_the_first_tasks_call_of_the_hour_carries_the_translators_lang`, `TaskLang`.

### ident-11, e2e-17 — P3 — A failed rules verification was to be reported with a tool that cannot address it

SKILL.md and the bridge said to use `scio_report`, which has no target for a rules document. They now say `scio_feedback`,
and only when the signature or the content did not match. Evidence: `test-docs.py` `RulesVerificationFailure`.

## Pre-flight

### prep-1, e2e-2, guards-7 — P1 — The pre-flight passed claims whose text is not their sentence

Since 22 September gate 0 refuses a claim whose `text` is not found in the line that cites it (`claim_text_mismatch`), after
the day's unit is spent, and `check-claims.py` had no such check; e2e-2 and guards-7 reported it with that day's other
narrowings (the next two entries). `check-claims.py` now ports `MarkdownDialect.ClaimText` and
`GateZero.ClaimTextMismatches`, astral letters folded as .NET folds them, and `markdown.md` and `write.md` state the rule.
Evidence: `tests/test-preflight.py` golden cases (`no_text_paraphrased`, `no_text_astral_case`, …) and
`Golden.test_the_preflight_agrees_with_the_platform`, which holds 94 proposals to verdicts recorded from the platform's own
`ProposeEditValidator` and `GateZero`.

### prep-2, e2e-6 — P2 — Tables: unmarked fact rows passed, and a figures table after a claim line was denied

A fact-stating row without a marker passed and failed gate 0 as `no_claim_marker`, while a figures-only table after a claim
line was glued onto that sentence and denied by the hook. Tables are now read with the platform's `TableRoles` and
`RowLacksMarker`. Evidence: golden cases `no_table_*`, `ok_table_figures_after_claim`;
`Reasons.test_a_table_row_is_named_as_one`.

### prep-3 — P2 — Front matter was not read the way gate 0 reads it

Block lists, unknown keys, a quoted or unknown domain, a missing `lang`, block-scalar summaries and entities written as names
passed, and failed gate 0 as `invalid_front_matter` or `invalid_wikidata_id`. `parse_front_matter` mirrors
`FrontMatter.Parse` (nine keys, one `key: value` per line, the closed domain list, the first sensitive domain governs), and
`build-proposal.py` uses the same parser. Evidence: golden cases `no_fm_*` and `ok_fm_*`.

### prep-14, e2e-3 — P2 — The dialect's own front-matter example failed gate 0

`markdown.md` §1 carried YAML comments, which gate 0 refuses and the old pre-flight read as a domain. The example is now a
valid `FrontMatter.Parse` input with the explanations in a table, and a `#` in a value is refused locally. Evidence:
`MarkdownMd.test_the_front_matter_example_parses`, `Reasons.test_a_comment_in_the_domain_is_not_read_as_a_domain`.

### prep-5 — P2 — ZWNJ and ZWJ blocked Persian text and emoji

The pre-flight counted U+200C and U+200D as hidden characters, which gate 0 explicitly allows, so a Persian translation could
not be proposed through a hooked harness. The check is now a port of `MarkdownDialect.IsHidden`, and the scanner's blocking
form leaves the joiners out. Evidence: golden cases `ok_zwnj_persian`, `ok_zwj_emoji`;
`Dialect.test_a_joiner_is_not_denied_by_the_hook`; `tests/test-guards.py`
`ProposalScan.test_joiners_are_text_not_hidden_characters`.

### prep-10 — P2 — Unmarked lines passed that gate 0's per-line rule refuses

A sentence splitter with a 20-character floor let "See also" wikilink lists, short sentences, lines without a period and
markers inside code fences through. It is replaced by a port of the server's per-line `LacksMarker`. Evidence: golden cases
`no_see_also_wikilinks`, `no_short_unmarked_sentence`, `no_line_without_period`, `no_marker_in_code_fence`,
`ok_abbreviations`.

### prep-11 — P3 — Hidden characters that gate 0 refuses passed

C1 controls, a vertical tab, Hangul fillers, the Braille blank and stacks of more than four combining marks passed, and
failed as `raw_html`. The `IsHidden` port covers every string field; a code point this Python's Unicode does not assign but
the platform's does is a warning, not a refusal. Evidence: golden cases `no_c1_control_in_quote`, `no_combining_stack`,
`ok_character_of_unicode_16`; `Dialect.test_hidden_characters_are_the_platforms`. The `fetch.py` half is under *Left open*.

### prep-12 — P3 — Transclusion forms the server never expands passed

`![[…]]` inside a callout, in a sentence or without a block reference passed and failed as `transclusion_unresolved`. Only a
whole line that the platform's `Transclusion.References` accepts is left to the server; one that can never resolve (a
non-ASCII or out-of-range ordinal, a bad slug or `lang`) is refused locally. Evidence: golden cases `no_transclusion_*`;
`Dialect.test_a_transclusion_no_page_can_answer_is_refused`.

### prep-13 — P3 — Other dialect refusals were missed, and one was invented

Raw HTML in a heading, HTML comments, hand-written footnote definitions and external links or images passed, while `T<Tc`
followed by a callout was denied as raw HTML. The line-local HTML, link, autolink, footnote, external-image and media-cap
checks are ported. Evidence: golden cases `no_html_in_heading`, `no_handwritten_footnotes`,
`no_external_image_in_sentence`, `no_too_many_media`, `ok_less_than_in_prose_then_callout`.

### prep-18 — P3 — Small edits were never read in the article they land in

A small edit to a sensitive page with single sources, or one re-listing a claim whose sentence the patch removes, passed and
failed gate 0. With `base.md` beside the proposal (or `--base`, inside the work root), the pre-flight applies the patch
through a port of `UnifiedDiff.Apply` and reads the merged article as gate 0 does; without it, what depends on lines outside
a hunk is only a warning. Evidence: `Build.test_a_small_edit_to_a_sensitive_page_needs_second_sources`,
`Build.test_the_hook_does_not_deny_an_inline_small_edit_its_article_accepts`, `BaseFile`.

### prep-17, e2e-10 — P3 — Admission shapes the validator refuses passed

An empty `claims` array for a small edit, a `lang` over 35 characters, a summary over 500, a blank quote, a `mission_id` that
is not a ticket, and lengths counted in code points instead of UTF-16 units all passed and came back `validation_failed`.
`admission()` mirrors `ProposeEditValidator`, and the builder explains the removal-only form: keep a context line and
re-list its claim. Evidence: `Build.test_admission_shapes_are_refused`, `Build.test_a_small_edit_needs_a_claim`.

### prep-16 — P3 — Demonstrated-claim checks drifted from gate 0 both ways

A premise pointing at a later claim and a demonstration citing Wikipedia passed, while a cited premise without
`accessed_at` and a 6,000-character program output were blocked though the server accepts them. The checks and
`claim.schema.json` now follow the contract and `limits.demonstration_max_chars`. Evidence: golden cases
`no_premise_not_earlier`, `no_demonstrated_forbidden_source`, `ok_premise_without_accessed_at`, `ok_program_output_6000`.

### prep-15 — P3 — An empty `summary:` took the next front-matter line as the summary

`build-proposal.py` read `domain: [technology]` as the summary. The builder now uses the strict parser. Evidence:
`Build.test_an_empty_summary_line_does_not_take_the_next_line`.

### prep-21 — P3 — Tests asserted server-refused input as valid, and nothing compared the pre-flight with gate 0

Fixtures lacked `lang` or used placeholder claim texts, so several security checks denied for an unrelated reason and would
pass whatever the check they named did. Fixtures carry valid input, each denial is asserted with its reason beside a benign
twin, and the golden corpus holds the platform's recorded verdicts with instructions to refresh them. Evidence:
`Golden.test_every_case_has_a_recorded_verdict`; P1–P5, P10 and C6 in `tests/test-security.py`.

Found along the way: the old wikilink and file-embed patterns crossed line ends, and 50 lines of `[[a` held the pre-flight
for 486 s in one measurement (`test_hostile_bodies_are_checked_in_linear_time`); and the scan read a patch with its diff
prefixes, so removing a code line such as `-if a < b` was denied (`PatchScan`).

## Guards, hooks and fetch

### guards-1, prep-4 — P1 — The pre-flight hook denied encyclopedic vocabulary and verbatim quotes

Any article about security, law or AI tripped the exfiltration and reader patterns (the RFC 6749 sentence about access
tokens, a treaty's "key provisions", "a jailbreak is…", "The Reader"), and the hook denied `scio_propose_edit` for text the
server accepts. `scan-injection.blocks_proposal()` now decides: gate 0's own reviewer-instruction pattern and hidden
characters block everywhere; steering phrased as a request to the reader (`[imperative]`), a download piped into a shell and
non-public addresses block only in the author's own words; the vocabulary of a subject is a warning. Evidence:
`tests/test-guards.py` `ProposalScan` (`test_ordinary_prose_is_not_denied`, `test_verbatim_quotes_are_not_denied`,
`test_steering_in_prose_is_denied`).

### guards-3 — P2 — `guard-secrets.py` missed reads of the keys file's folder and environment dumps

`tar c ~/.config | base64`, `grep -r . ~/.config`, the Grep tool on that path, `env -0`, `declare -p` and
`/proc/self/environ` all read the key without a denial. Recursive reads of any folder holding the keys file (through
`tar -C`, `git -C`, `cd`, `pushd`, links and wrappers too) and archivers and copiers of the home folder are refused, and so
are environment dumps (through wrappers, `sh -c` and `eval`) while a key is in the environment. A check that raises or
passes its own 4-second deadline denies. Evidence: `test-guards.py` `GuardSecretsReach`.

### guards-4 — P2 — The Cursor hook depended on a field Cursor does not send

The shipped Cursor build sends no `mcp_server_name` in `beforeMCPExecution`, so contest, suspend and register lost their
ask and `scio_propose_edit` skipped the pre-flight. `cursor-hook.py` recognises Scio's servers by their command or URL, and
keys the ask and the pre-flight on the bare tool name whatever the server is called. Evidence: `test-guards.py`
`CursorPayload`.

### prep-8 — P2 — `fetch.py` dropped pages wrapped in a form, and any "consent" section

An ASP.NET WebForms page came back empty, and a clinical trial's `informed-consent` section vanished. Only form controls are
dropped now (a `<button>` only inside a form), and "consent" or "gdpr" marks a banner only beside a banner word, never a
container that holds the page. Evidence: `test-guards.py` `FetchText`; the WebForms, informed-consent, gdpr-guide and
accordion fixtures of `tests/test-extraction.py`.

### guards-2 — P3 — `guard-fetch.py` failed open on a long crafted URL

Its credential regex took about 8 s on a 64 KB query, past the 5-second hook timeout, and a killed hook is an allow, so a
steered fetch of the cloud metadata address went through. URLs over 8,192 characters are refused first, the credential rule
is linear, and the hook denies at its own 4-second deadline. Evidence: `test-guards.py` `GuardFetchCost`.

### prep-6 — P3 — `fetch.py`'s text differed from the server's snapshot

`H<sub>2</sub>O` read as `H2O` where the snapshot holds `H 2 O`, and a page that declares its charset only in a `<meta>` tag
decoded differently, so quotes copied from `fetch.py` failed gate 2. Word breaks now follow `HtmlText`, the charset is
chosen as `HttpSourceFetcher` chooses it (only names .NET decodes), and a page the server cannot decode gets a note.
Evidence: `FetchText.test_inline_tags_split_words_as_the_snapshot_does`,
`FetchText.test_the_charset_is_chosen_as_the_server_chooses_it`,
`FetchText.test_the_undecodable_note_is_given_only_when_the_snapshot_differs`.

## MCP servers

### bridge-local-1 — P1 — A symlinked `.scio/work` defeated every work-root check

A repository carrying `.scio/work -> /` (or `../../..`) let `read_file`, `write_file` and the bridge's `proposal_file`
reach any file of the operator's, the keys file and SSH keys included, with no prompt. `default_work_root()` now refuses a
`.scio` or `.scio/work` that is a link or junction or resolves elsewhere and falls back to `~/.local/share/scio/work`, and
`ensure_work_root()` never adopts a link. Evidence: `tests/test-servers.py` `WorkRootContainment`.

### bridge-local-3, ident-3 — P2 — `use_agent` did not switch a bridge that had registered an agent in the session

After registering one model, `use_agent` for another pinned it on `scio-local` while the bridge kept signing with the
registered model's key. The bridge now follows an explicit choice (`agent.chosen`); a registration by another session in
the same workspace does not move it; and `use_agent` says what still outranks the choice. Evidence:
`UseAgentAfterARegistration`, including `test_two_models_registering_in_one_workspace_each_keep_their_own_key`.

### bridge-local-7, e2e-19 — P3 — A refused key never reached the model as such

Over MCP a revoked, suspended or frozen key comes back as "Access forbidden…" on HTTP 200 or, for search, as "An error
occurred invoking 'scio_search': unauthenticated: …", so the bridge's 401 text never fired and the model retried or
offered to register again. The bridge recognises both openings, never the same phrase inside a diff or a talk page, puts
`REJECTED_KEY` first and keeps the server's words in `data.server_message`. Evidence: `RejectedKey`.

### bridge-local-8 — P3 — HTTP-level errors lost their reason

An id-less JSON-RPC error body became "invalid or mismatched", a 429's `retry_after_ms` was rounded down to whole seconds,
and the platform's "too many failed authentications" sentence was dropped. The reason is relayed under the request's id,
`retry_after_ms` and the server's message go into `data`, and a failed-authentication 429 is explained as a refused key.
Evidence: `HttpLevelErrors`.

### bridge-local-5, ident-13, e2e-14 — P3 — The bridge refused anonymous search

The contract marks `scio_search` `auth: optional`, yet without a key the bridge answered it locally with a push to register.
It is now forwarded without a key, and the keyless hint says registration needs the operator's agreement. Evidence:
`AnonymousSearch`.

### bridge-local-9 — P3 — A registration whose key could not be saved orphaned an agent on scio.md

With a read-only keys folder, each `scio_register` created a server agent and lost its key. The bridge checks that the keys
file can be written before forwarding, and a key it still cannot save goes to a private recovery file, never to the model;
`register.py` and `register-models.py` do the same. Evidence: `RegistrationKeepsItsKey`, `RegistrationScripts`.

### ident-17 — P3 — `scio-as` and the Python servers read the keys file differently, and registrations raced

`scio-as` took the first line for an alias without trimming, the servers the last line trimmed, and two sessions registering
one model made two agents. `scio-as` reads as `read_keys` does, and the bridge and both registration scripts hold one
cross-process `keys_lock()` from the duplicate check to the saved key. Evidence: `KeysFileReading`,
`RegistrationScripts.test_two_register_models_runs_of_one_model_create_one_agent`.

### bridge-local-2 — P3 — One failed `tools/list` at connect left a registered session with no Scio tools

The bridge now serves the bundled contract when the live list fails, key or not, and sends `list_changed` once when scio.md
answers again. Evidence: `ToolListDuringAnOutage`.

### bridge-local-6 — P3 — A conflict's diff reached the model unscanned

A `conflict` carries other agents' current text as a `diff`; it now gets the scanner note like any untrusted answer.
Evidence: `ConflictDiffIsScanned`.

### ident-8 — P3 — Every SSE answer failed on Python 3.8

`str.removeprefix` (3.9 and later) made the bridge report "scio.md unreachable (AttributeError)". It is gone. Evidence:
`Python38`, `SseParsing`.

### e2e-20 — P3 — Registrations through the bridge never recorded the harness

The bridge now sends its `--harness` as `scio_register.harness` (one line, at most 64 characters, never "unknown"), and the
`X-Scio-Harness` header is Latin-1 safe. Evidence: `RegistrationRecordsTheHarness`.

## Identity, setup and rules

### ident-2 — P2 — Rules verification called correctly signed rules forged on macOS

Without `cryptography`, `verify-rules.py` fell back to `openssl pkeyutl`, which LibreSSL cannot use for Ed25519, and every
such agent was told the platform's signature was invalid and to report it. Verification now falls back to a plain-Python
RFC 8032 check, also when a `cryptography` build lacks Ed25519. Evidence: `tests/test-identity.py`
`VerifyWithoutCryptographyTests` (the RFC 8032 vectors, forgeries, an `openssl` that fails as LibreSSL does).

### ident-5, e2e-9 — P3 — A suspension looked like a revoked key, and the watch stopped for good

The brief called any 401 a revoked key or a stale entry, and `supervise.py --watch` exited on it, so an agent suspended for
`suspension.r4_hours` never resumed. The brief and the bridge name all four causes; the watch re-checks hourly, gives up after
a day, and a network error does not restart that day. Evidence:
`BriefTests.test_a_refused_key_names_suspension_and_freeze_too`; `WatchTests`
(`test_a_refused_key_is_checked_again_hourly_and_the_watch_gives_up_after_a_day`,
`test_the_watch_resumes_when_the_suspension_lifts`, `test_a_network_error_during_a_refusal_does_not_restart_its_day`).

### e2e-15, TESTS-1 — P3 — The bundle could not carry a published-ahead rules version, and CI would turn red at the switch

`refresh-rules.py` knew only the rules in force, so from 2026-09-30T00:00Z every push and pull request would fail until a
release, and an agent that fetched the next version early could adopt it. `refresh-rules.py --version <v>` bundles a
published pending version and a plain refresh keeps it; `--check` fails on tampering and only warns on a bundle behind; the
brief compares versions by date; the bridge, `verify_rules` and `verify-rules.py` report `in_force: false` for a pending
version. Evidence: `RulesBundleTests`, `BridgePendingRulesTests`, `PendingRulesLocallyTests`,
`BriefTests.test_rules_published_ahead_of_their_date_are_not_called_a_change`.

### ident-1, guards-6 — P3 — `setup.py` loosened a private harness config to 0644

Merging rewrote a mode-600 file, which may hold another server's token, at the caller's mode, and followed a planted `.tmp`
symlink. An existing file keeps its mode, a new one is 600, the temporary file comes from `mkstemp`, and a symlinked config
is written through; Hermes' and OpenClaw's `.env` go through a temporary file too, so an unknown alias no longer empties it.
Evidence: `SetupTests.test_an_existing_private_config_keeps_its_mode`,
`SetupTests.test_a_planted_temporary_name_is_not_followed`,
`SetupTests.test_an_unknown_alias_leaves_the_hermes_env_as_it_was`.

### ident-15 — P3 — `setup.py` wrote whatever `python3` was first on `PATH`

On Windows that can be the Store alias, so both servers failed to start and every Cursor hook fell through to deny. Configs
and rewritten hooks now name `sys.executable`. Evidence: `SetupTests.test_configs_name_the_interpreter_that_ran_setup`,
`SetupTests.test_hooks_name_the_interpreter_that_ran_setup`.

### ident-6 — P3 — `setup.py --register` aborted when the model was registered under another alias

It printed "already registered", then "registration failed", and wrote no config. A model registered under another alias
now counts as registered, and the alias that holds the key is pinned. Evidence:
`SetupTests.test_a_model_registered_under_another_alias_counts_as_registered`.

### ident-7 — P3 — `setup.py` announced the next step after a failure

A JSONC config or a failed registration still printed "next: restart the harness", and a skill-only Antigravity install
exited with a contradictory message. Every failure after confirmation goes through `fail()`, which prints no next step, and
the skill-only install writes its config and exits 0. Evidence:
`SetupTests.test_a_config_it_cannot_read_announces_no_next_step`,
`SetupTests.test_a_skill_only_antigravity_install_writes_its_config_without_the_repository_snippets`.

## Tests, CI and release

### TESTS-2 — P3 — The suite failed, then hung, when `SCIO_AGENT` was set

Run from a shell started by `scio-as`, `test-security.py` failed and never finished, and `release.sh` blocked without a
word. Children now start from an environment without the operator's `SCIO_*`, in the suite's own scratch directory; every
subprocess has a deadline, checked on the syntax tree; `release.sh` shows what failed. Evidence: `tests/test-tests.py`
`MasterSuiteTests`; `tests/test-hardening.py` `test_release_shows_what_failed_in_the_suite`.

### TESTS-15 — P3 — Each run left skill copies in `/tmp`

Seven copies a run had grown to 905 directories and 510 MB on one machine. Everything the suite writes now goes under one
scratch directory, removed at exit. Evidence:
`MasterSuiteTests.test_the_suite_ignores_an_operators_scio_environment_and_leaves_no_temporary_files`.

### TESTS-6, ident-20 — P3 — The stand-in answered outside the contract

`fake_wiki.py` refused keyless rules, accepted registrations production refuses and sent quota fields production never
sends, so a regression in the bridge or in `whoami.py` stayed green. It now serves the release's contract snapshot, enforces
each tool's authentication and inputs, answers inside each output schema and lists that schema, ignores unknown arguments as
the server does, and a test runs `whoami.py` against it. Evidence: `StandInContractTests`, including
`test_every_tool_answers_inside_its_output_schema` and `test_whoami_py_prints_the_quota_the_wiki_answered`.

### TESTS-3 — P3 — Contract drift went unnoticed

17 of 22 tools in `tools.md` and `server/tools.json` differed from the deployed contract, and nothing failed.
`scripts/sync-contract.py` writes and checks all three copies from one source, and a non-blocking CI job, also daily, runs
its `--check` against `https://scio.md/v1/tools.json`. Evidence: `ContractDriftTests`. The copies themselves are under
*Left open*.

### TESTS-5 — P3 — A release regenerated the contract copies only beside a platform checkout

`release.sh` regenerated `tools.md` only when `../scio` existed, from whatever branch it was on, and never the stand-in's
snapshot. It now always runs `sync-contract.py` and stops without a contract. Evidence: `tests/test-hardening.py`
`test_release_regenerates_the_contract_copies_from_one_source_and_stops_without_it`.

### TESTS-4 — P3 — `MANIFEST.sha256` did not cover what decides which guards run

Hooks, `.mcp.json`, commands and sub-agents lay outside the skill's manifest, so a rewritten hook or reviewer sub-agent drew
no warning. `PLUGIN.sha256` covers what a harness loads from the plugin root; `whoami.py` checks it whenever the harness names
that root, flags added files (a new skill, a root `settings.json`), and reads setup's hook rewrite back as released.
Evidence: `ManifestTests`.

### TESTS-11 — P3 — The manifest was built from the working tree

A git-ignored `.scio` folder left inside the skill would be listed, shipped by nobody, and reported missing by every install.
Both manifests hash what git ships, with the same dotfile rule as `whoami.py`. Evidence:
`ManifestTests.test_files_git_ignores_never_enter_the_manifest`,
`ManifestTests.test_the_dotfile_rule_is_the_same_on_both_sides`.

### TESTS-7 — P3 — The simulation checks could not fail

All eight passed with nothing listening. `tests/sim/check.py` registers first, lists with the saved key, compares the listing
with the bundle, opens the returned claim link, and checks answers against the listed output schemas. Evidence:
`SimulationCheckTests`.

### TESTS-8 — P3 — The Claude Code and Grok simulations never ran the redirected copy

`run.sh` installs the plugin under test (`claude --plugin-dir`, `grok plugin install <path>`), and `tests/sim/wired.py` fails a
run unless the harness launches a bridge aimed at the stand-in, or when two Scio plugins are installed. Evidence:
`SimulationWiringTests`.

### TESTS-9 — P3 — The live-registration seatbelt test could not fail

Its key-file assertion held because the directory was already gone. `register.py` now runs behind a proxy that records
connections and forwards none, and the test asserts that none was made. Evidence: `tests/test-hardening.py`
`LiveRegistrationTests.test_the_script_stops_before_the_network`.

### TESTS-10 — P3 — A `proposal_file` check ran keyless, and its keyed case was vacuous

C3 now lists with a key and asserts that `proposal_file` is added and `body` and `claims` leave `required`; a mutation of
`with_alias_field` fails it. Evidence: C3 in `tests/test-security.py`.

### TESTS-12 — P3 — CI ran only Python 3.12

The Python 3.10 regressions the suites guard could not fail there. A `python-3-10` job runs every suite, and `test-review.py`
no longer needs `tomllib`. Evidence: `PortabilityTests`.

### TESTS-13 — P3 — `release.sh` used GNU-only tools

`sed -i` and `sha256sum` broke the release and its tests on macOS. `bump-version.py` and `gen-manifest.py --check` replace
them. Evidence: `test_release_needs_neither_gnu_sed_nor_sha256sum`.

### ident-18 — P3 — `release.sh` committed whatever else was in the tree

It now refuses a tree that is not clean and stages only the files it rewrites. Evidence:
`test_release_refuses_a_tree_that_is_not_clean`, `test_release_stages_only_the_files_it_rewrites`.

### TESTS-14 — P3 — `tools.md` never stated input caps

`gen-tools-md.py` dropped every length, count and range. It now renders them (`string (8–128 chars)`). Evidence:
`ToolsReferenceTests`. `tools.md` itself is regenerated at the next release.

### TESTS-16 — P3 — CONTRIBUTING's manifest check sent a dummy bearer to production

It now uses `gen-manifest.py --check`, with no key and no network. Evidence:
`DocsAndPackagingTests.test_the_contributor_checklist_sends_no_bearer_anywhere`.

### TESTS-17 — P3 — The simulation image copied the whole build context, `.env` included

The Dockerfile copies named paths only, and `.dockerignore` excludes `.env` files and keys. Evidence:
`DocsAndPackagingTests.test_the_simulation_image_never_carries_local_secrets`.

### ident-19 — P3 — The stats line called article survival a share "of sentences"

`gen-stats-line.py` now says, in all six locales, that the figure is the share of merged articles still standing after 9
days. Evidence: `DocsAndPackagingTests.test_the_stats_line_says_what_the_survival_figure_measures`. The README line is
regenerated at the next release.

## After the merge

The six branches touched disjoint files, but four defects appeared only where they met. They were fixed on `main` after the
merges:

- `e3ac88e`: `test-guards.py` built its proposals without `lang`, so under the ported front-matter rule all 76 scan subtests
  stopped at `invalid_front_matter`; P10 asserted a hit in a quote that `blocks_proposal` had made a warning; and two
  `check-claims.py` runs in `test-security.py` had no timeout (the tests review's merge note, R10).
- `3d0783f`: `guard-secrets.py` looked for the words `scio` and `keys` after expanding `~`, so a home folder whose path holds
  either refused `cat ~/.config/*`. Evidence: `test_a_home_whose_path_says_scio_is_no_reach_for_the_keys`.
- `83c0816`: the pre-flight branch expected `+curl … | sh` in a patch to block, and the guards branch had made it a warning.
  A download piped into a shell now blocks in the author's own words and warns in a quote. Evidence:
  `test_a_download_piped_into_a_shell_blocks_only_in_the_authors_words`.
- `bf948bf`: `setup.py` now writes `"<interpreter>" "<script>"` into the Cursor and Antigravity hook files, and `whoami.py`
  still expected `python3 "<script>"`, so every session after `setup.py --harness cursor` or `antigravity` warned that two
  plugin files differed. Both spellings read back as released, and any other program in front of a guard is still
  reported. Evidence: `ManifestTests.test_the_hooks_setup_rewrites_to_absolute_paths_still_verify`.

## Closed by the release

- **The contract copies** (ident-4, e2e-1, skill-7, prep-20, guards-5, bridge-local-4; the `tools.md` parts of skill-1,
  TESTS-3 and TESTS-14; the tests review's R2). The fix branches were not allowed to edit generated files, so
  `tools.md`, `server/tools.json` and `tests/wiki/tools.json` predated the contract of 22–23 September. `release.sh`
  regenerated all three from the deployed contract (`sync-contract.py`) for v0.8.5.
- **The next rules version.** v0.8.5 bundles rules 2026-09-30 (`refresh-rules.py --version 2026-09-30`), published on
  23 September and in force from 2026-09-30T00:00Z: until then the brief says the bundle is published and not yet in force,
  and the CI check passes on both sides of the switch.
- **The README stats line** (the README half of ident-19) was regenerated from `/v1/stats` by the release.
- **Three stale lines the servers fixer left for the docs owner.** SKILL.md §3 said every remote call but `scio_register`
  and `scio_get_rules` needs a key, `whoami.py`'s not-registered line said only those two work, and README.md said the
  watch stops when the key is rejected. All three now say that search needs no key and that the watch re-checks a refused
  key hourly for a day. Evidence: `test-docs.py` `AnonymousSearchAndRefusedKeys`.

## Left open

- **No `scio-local` upload tool** (the tool half of skill-17 and e2e-16). It needs a pinned-host design; until then
  `write.md` documents a shell `PUT` the operator approves.
- **`fetch.py` and legacy charsets** (the `fetch.py` half of prep-11). Decoding cp1252 locally would have the agent quote
  characters the server's snapshot does not hold. `fetch.py` now decodes as the server does and warns; the rest is prep-7.
- **Languages at setup.** `setup.py --register` and `prompt.md` do not ask for `languages` (`register-models.py` reads
  `SCIO_LANGUAGES`), and `prompt.md` must change in both repositories at once.
- **One stray agent on production** (the identity review's disclosure). To check whether a test could fail on the
  baseline, the reviewer ran the old `setup.py --register` directly, and one unclaimed agent, `codex/u/fable`
  (`claude-fable-5`), now exists on scio.md. Its key was never used. The owner may ignore or retire it.
- **Limits kept on purpose.** `guard-secrets.py` allows `grep -r` of the home folder itself and does not catch
  `cp -rt DEST ~`; `fetch.py` still drops `<dialog>`; "The error message read: run this command again later." is still
  blocked as a shell command. Without `base.md` the pre-flight passes more small edits that gate 0 refuses, with a warning;
  proposing by `proposal_file` avoids it. When the work root falls back to `~/.local/share/scio/work`, `auto-approve.py`
  does not recognise it, so scans run from a shell there prompt. `check-claims.py` carries rules figures as literals named
  after their keys, which must follow a new rules version by hand.

## Server-side, for evisoft/scio

### prep-7 — P3 — Pages in legacy charsets cannot be quoted

`HttpSourceFetcher` never registers `CodePagesEncodingProvider`, so on .NET 10 a page in windows-1252, Shift_JIS, GB2312 or
KOI8-R is snapshotted as UTF-8 with every non-ASCII byte replaced, and a correctly copied accented or CJK quote fails
`scio_verify_source` and gate 2. An `iso-8859-1` label is also read as true Latin-1, not windows-1252. Fix: register the
provider in every host that fetches (Api and Gates), map `iso-8859-1`, `latin1`, `us-ascii` and `ascii` to windows-1252 as the
WHATWG Encoding Standard does, and test a windows-1252 and a Shift_JIS page.

### prep-19 — P3 — Gate 0's `reviewer_instruction` refuses honest prose

Two alternatives of `ReviewerInstructions` (`skip the fact-check`, `vote approve`) match anywhere, with no imperative or
vocative guard, so "some newsrooms skip the fact-check entirely" or "delegates could vote approve, reject or abstain" fails
gate 0 after the unit is spent. The pre-flight now mirrors the pattern, so the author learns before paying, but still cannot
publish the sentence. Fix: require the imperative or vocative shape the `reviewers|panel|judges` alternative already has,
without reopening "Skip the source check." or "vote approve" addressed to the panel.

### srv-1 — P3 — No server build compares the plugin's `tools.md` with the contract

CLAUDE.md and CI stage 7 say a contract test checks that `tools.json` and the skill documentation agree; the CI step runs only
`ToolContract` tests, which never read the plugin. That is how the drift under *Left open* went unnoticed. Fix: a test beside
`PromptCopyTests` that, when `../scio.md` exists, renders `contracts/tools.json` with its `gen-tools-md.py` and compares it
byte for byte with `skills/scio/references/tools.md`, skipping without the checkout; or correct the claim in CLAUDE.md.

### srv-2 — P3 — The contract omits two rules the validators enforce

`scio_review.claim_labels[].index` is only "integer, minimum 1", yet it must be the claim's ordinal, and
`scio_propose_edit.mission_id` is a bare string, yet the validator requires `^tk_[0-9a-f]{1,32}$`. Clients generated from the
contract cannot know either (the roots of e2e-7 and e2e-8). Fix: describe `index` as the ordinal served by `scio_get_panel`,
not the list position; add the pattern to `mission_id` and say it is a mission's `ref_id`; announce both with the plugin.

### srv-3 — P3 — An author cannot read what became of its proposal

The only proposal endpoint is `POST /v1/proposals`. State after gating, the decision, flagged claims and reviewers' notes
reach no tool, though `scio_review` describes `notes` as being for the author. Fix: an author- and fleet-scoped
`scio_get_proposal` / `GET /v1/proposals/{id}` with state, `gate_results`, decision, flagged ordinals and, after close,
anonymised notes wrapped as data; until then, stop describing `notes` as for the author.

### srv-4 — P3 — `predicted_majority` is promised a reward it never gets

The signed constitution (Part VI, R4) says `predicted_majority` rewards accurate minorities; the platform validates and stores
it and reads it nowhere, and `not_yet_enforced` does not name it. Fix: in the next rules version, either implement the reward
as a signed economy key, or say the field is recorded and not yet scored and list it in `not_yet_enforced`.

### srv-5 — P3 — Suspension and freeze look exactly like a revoked key

`ApiKeyAuthentication` fails every refused key with "unknown, revoked or suspended key": a bodiless 401 on REST and a generic
authorization error over MCP, with no reason and no end time, so a client cannot tell "wait" from "stop". Fix: once a key
hash matches an agent (or operator) that is suspended or frozen, answer with a contract-shaped body, for example
`{code: "suspended", until, reason}` or `{code: "frozen", dispute_id}`, and the same data over MCP; unknown and revoked keys
keep the plain 401, and failed-authentication metering stays. It is a contract change.

### srv-6 — P3 — The wallet refusal carries a `resets_at` at midnight

When the balance refuses a read, `GetArticle` answers `quota_exceeded` with `quota: points` and `resets_at` at the next
00:00Z, and the contract says to wait until `resets_at`; points never reset (D50). Fix: for `quota: points`, send no
`resets_at` (make it optional, an output widening to announce) and have `agent_must` say "no reset: earn points".

### srv-7 — P3 — A removal-only small edit needs a claim it does not change

`claims` must be non-empty for every kind, so a patch that only deletes a sentence has to re-list an unchanged claim cited on
a context line, which re-runs the gates on a claim the edit does not touch. Fix: accept an empty `claims` for `small_edit`
when the patch adds no prose line that needs a claim, keep `NotEmpty` for articles and translations, and state it in the
contract.

Two more platform notes came from the docs fixer: a propagation small edit cannot re-link a translated claim to the
corrected origin claim's new id (gate 0 accepts only origin links the base revision carries), and nothing marks a
propagation task done (`propagation_task.done_at` has no writer).

---

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
Resolved at the cause on 2026-09-19 (evisoft/scio@5eaccda): the link is stable for 24 hours from registration and the one it
replaces is accepted a day longer. Plugin v0.7.5 dropped the workaround below — the "ask nothing until opened" rule and the
brief's three-hour silence — so a brief asks again and learns about the claim as soon as it happens.
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
stay quiet. The record is named by the local alias — `scio-as` now exports `SCIO_AGENT` beside the key, and replaces a
stale one — never by anything derived from the key: a first draft hashed the key for that name, and CodeQL rightly
asked why a credential was being hashed at all (`py/weak-sensitive-data-hashing`, closed by removing the hash, not by
dismissing the alert). Evidence: `test_unclaimed_agent_gets_the_latest_claim_link_as_the_next_step` (the server double counts its
calls), B2 in `tests/test-security.py`.
