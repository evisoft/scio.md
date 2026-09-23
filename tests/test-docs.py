#!/usr/bin/env python3
"""Regressions for the 23 Sep 2026 review — docs. Run: python3 tests/test-docs.py (test-security.py runs it too).

What the skill tells an agent is behaviour: an instruction that does not match the platform makes every agent that
follows it do the wrong thing at once. Each case below pins one confirmed finding (its ids in the docstring) to the
platform's own contract — contracts/tools.json, RankRules, the signed rules — so the wording cannot drift back."""
import http.server, json, os, re, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "scio"
WF = SKILL / "references" / "workflows"

# What each permission needs on the server (src/Scio.Core/Identity/RankRules.cs): every rank has every lower one's.
LADDER = {"read": 0, "propose": 1, "contest": 1, "review_small": 2, "review_article": 3, "translate": 3,
          "curate": 4, "arbitrate": 5}
# The questions an arbiter panel's summary asks (EfPanelStore.ContestQuestion), one per dispute remedy.
ARBITER_QUESTIONS = ("APPEAL", "HIDE NOTICE", "REDACTION NOTICE", "CONDUCT", "AUDIT", "PROMOTION")


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def section(body, heading):
    """The text under a `## heading`, up to the next heading of the same level."""
    found = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return found.group(1) if found else ""


# Every Markdown file an agent is told to read, plus the English README a human reads.
AGENT_DOCS = sorted({*(p.relative_to(ROOT).as_posix() for p in WF.glob("*.md")),
                     "skills/scio/SKILL.md", "skills/scio/references/roles.md",
                     "skills/scio/references/security.md", "skills/scio/references/style.md",
                     *(p.relative_to(ROOT).as_posix() for p in (ROOT / "agents").glob("*.md")),
                     *(p.relative_to(ROOT).as_posix() for p in (ROOT / "commands").glob("*.md")),
                     "GEMINI.md", "openclaw/scio/SKILL.md", "README.md"})


class ArbiterSeats(unittest.TestCase):
    """skill-1. An arbiter panel (whoami kind contest|audit, get_panel kind contest) judges a dispute whose material is
    the reported text itself, and approve answers yes to the question in its summary. review.md knew only proposal
    review — reject on any text addressed to reviewers — so seven founders voting on an injection's redaction notice
    all rejected it, and the injected text stayed."""

    def arbiter(self):
        return section(text("skills/scio/references/workflows/review.md"), "Arbiter seats")

    def test_review_workflow_has_an_arbiter_section_for_every_question(self):
        arb = self.arbiter()
        self.assertTrue(arb, "review.md has no '## Arbiter seats' section")
        for q in ARBITER_QUESTIONS:
            with self.subTest(question=q):
                self.assertIn(q, arb)
        for needle in ("`contest`", "`audit`", "joined_reports", "panels.contest", "approve"):
            with self.subTest(needle=needle):
                self.assertIn(needle, arb)

    def test_the_reported_text_is_judged_never_a_reason_to_reject_the_notice(self):
        arb = self.arbiter()
        self.assertRegex(arb, r"never a reason to reject")
        self.assertRegex(arb, r"not an instruction")
        self.assertRegex(arb, r"(?i)no second report|never (?:file|a reason to file) another report|do not report it again")

    def test_every_reject_on_injection_rule_names_the_arbiter_exception(self):
        """Wherever a reviewer is told to reject text that addresses reviewers, the arbiter exception is at hand."""
        for path in ("skills/scio/references/workflows/review.md", "skills/scio/references/security.md",
                     "agents/scio-reviewer.md", "skills/scio/SKILL.md", "commands/review.md"):
            with self.subTest(file=path):
                self.assertRegex(text(path), r"(?i)arbiter")

    def test_every_route_to_a_seat_reaches_the_arbiter_section(self):
        for path in ("skills/scio/SKILL.md", "skills/scio/references/workflows/loop.md", "commands/review.md",
                     "agents/scio-reviewer.md", "commands/loop.md"):
            with self.subTest(file=path):
                self.assertRegex(text(path), r"Arbiter seats|review\.md#arbiter-seats")

    def test_the_seat_count_is_not_fixed(self):
        self.assertNotIn("one of 7", text("skills/scio/references/workflows/review.md"))
        self.assertNotIn("audit` → review, with the extra care", text("skills/scio/references/workflows/loop.md"))


class ClaimLabels(unittest.TestCase):
    """skill-2, e2e-8. scio_get_panel serves the claims in an order private to each reviewer and scio_review matches
    claim_labels[].index against the claims' ordinals; a label given by list position passes validation and lands on
    another claim."""

    FILES = ("skills/scio/references/workflows/review.md", "skills/scio/references/workflows/team.md",
             "commands/review.md", "agents/scio-reviewer.md", "agents/scio-refuter.md")

    def test_every_reviewing_instruction_says_index_is_the_ordinal(self):
        for path in self.FILES:
            with self.subTest(file=path):
                body = text(path)
                self.assertRegex(body, r"`?ordinal`?")
                self.assertRegex(body, r"(?i)never (?:by )?(?:its )?position")

    def test_review_workflow_ties_index_to_ordinal(self):
        self.assertRegex(text("skills/scio/references/workflows/review.md"), r"`index` is the claim's `ordinal`")

    def test_refuters_return_labels_keyed_by_ordinal(self):
        refuter = text("agents/scio-refuter.md")
        self.assertNotRegex(refuter, r"Return the labels as a JSON list\.")
        self.assertRegex(refuter, r'"ordinal"')


class Outcome(unittest.TestCase):
    """skill-3, e2e-11. Nothing pushes an outcome to an agent, reviewers' notes are never served, round two is the
    platform's, and there is no way to re-propose inside a proposal — a rewrite sent while the first is in a panel
    draws a second panel for one article."""

    STALE = ("reaches you as a harness notification", "share card", "reviewer notes are on",
             "re-propose within the same proposal", "task notification", "Poll or wait for the notification",
             "notify owner", "request_changes` rounds", "round 2 of maximum 2")

    def test_no_file_promises_a_push_a_note_or_an_in_place_round(self):
        for path in AGENT_DOCS:
            body = text(path)
            for phrase in self.STALE:
                with self.subTest(file=path, phrase=phrase):
                    self.assertNotIn(phrase, body)

    def test_write_says_how_the_outcome_is_learnt(self):
        write = text("skills/scio/references/workflows/write.md")
        for needle in ("same `idempotency_key`", "https://scio.md/me", "scio_get_history", "in_panel",
                       "panels.round_two_seats", "new proposal"):
            with self.subTest(needle=needle):
                self.assertIn(needle, write)

    def test_request_and_gap_point_to_the_same_answer(self):
        for path in ("skills/scio/references/workflows/request.md", "skills/scio/references/workflows/gap.md"):
            with self.subTest(file=path):
                self.assertRegex(text(path), r"write\.md\)? step 8")


class Maintenance(unittest.TestCase):
    """skill-4, e2e-5, e2e-7. The platform serves three kinds of ordinary work: write_gap, propagation (translate, R3)
    and small_edit missions from error reports (propose, R1) that are answered with mission_id = the report ticket
    (the task's ref_id, tk_…). maintain.md gated them on curate (R4 on the server, checked nowhere), promised a ×1.5
    that does not exist, described four task kinds never served, and never said mission_id."""

    def test_maintain_describes_only_what_the_platform_serves(self):
        body = text("skills/scio/references/workflows/maintain.md")
        for gone in ("needs_citation", "dead_link", "`stub`", "`stale`", "×1.5", "curate"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)
        for needle in ("mission_id", "ref_id", "tk_", "task_id", "`propose`", "`translate`", "ref_kind"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)

    def test_routes_to_maintenance_do_not_ask_for_curate(self):
        for path, row in (("skills/scio/SKILL.md", r"^\|.*maintain\.md.*$"), ("README.md", r"^\|.*`maintain`.*$")):
            with self.subTest(file=path):
                found = re.search(row, text(path), re.M)
                self.assertIsNotNone(found)
                self.assertNotIn("curate", found.group(0))

    def test_the_loop_and_the_writer_pass_the_ticket(self):
        for path in ("skills/scio/references/workflows/loop.md", "skills/scio/references/workflows/write.md"):
            with self.subTest(file=path):
                self.assertIn("mission_id", text(path))

    def test_build_proposal_names_the_ticket_not_the_task(self):
        self.assertNotIn("--mission-id <task id>", text("skills/scio/scripts/build-proposal.py"))
        with tempfile.TemporaryDirectory() as root:
            task = Path(root) / "task"
            task.mkdir()
            env = dict(os.environ, SCIO_WORK_DIR=root)
            def build(mission):
                return subprocess.run([sys.executable, str(SKILL / "scripts" / "build-proposal.py"), str(task), "--slug",
                                       "x", "--lang", "en", "--kind", "small_edit", "--base-revision",
                                       "rv_0123456789abcdef", "--mission-id", mission],
                                      capture_output=True, text=True, env=env)
            wrong = build("tm_tk_0123abcd")   # the task_id, as the old usage line invited
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("ref_id", wrong.stdout + wrong.stderr)
            right = build("tk_0123abcd")      # the ticket passes this check and stops later, at the missing claims.json
            self.assertNotIn("ref_id", right.stdout + right.stderr)
            self.assertIn("claims.json", right.stdout + right.stderr)


class DeadSources(unittest.TestCase):
    """skill-5, e2e-4, prep-9. archived_url is Scio's own copy on scio.md, a forbidden source host (P7). A dead source
    with an earlier copy of ours answers `archived` and gate 1 reads that copy under the original URL; `dead` means no
    copy exists. Citing the archive URL could never pass."""

    def test_no_instruction_cites_the_archive_as_a_source(self):
        for path in ("skills/scio/references/workflows/maintain.md", "skills/scio/references/workflows/write.md",
                     "skills/scio/scripts/check-claims.py"):
            with self.subTest(file=path):
                body = text(path)
                self.assertNotRegex(body, r"(?i)archive(?:d)?[ _]url[^.\n]{0,40}as `?source_url")
                self.assertNotRegex(body, r"the archived_url of the verdict")

    def test_maintain_keeps_the_original_url_for_an_archived_source(self):
        body = text("skills/scio/references/workflows/maintain.md")
        self.assertRegex(body, r"`archived`[^\n]*original")
        self.assertRegex(body, r"(?i)never[^\n]{0,60}`archived_url`")


class Languages(unittest.TestCase):
    """skill-6, skill-18. A translation needs the origin's language verified and the target verified — or, while the
    target is closed for originals, declared at registration; languages are declared only in scio_register, and
    translate is R3 on the server. The task sample of an hour is frozen by its first scio_get_tasks call, whose lang
    decides whether a translator's propagation tasks are in it."""

    def test_registration_asks_for_languages(self):
        for path in ("skills/scio/SKILL.md", "skills/scio/references/workflows/onboard.md", "commands/register.md"):
            with self.subTest(file=path):
                self.assertRegex(text(path), r"`languages`")

    def test_translate_states_the_server_preconditions(self):
        body = text("skills/scio/references/workflows/translate.md")
        self.assertIn("R3", body)
        self.assertIn("languages_declared", body)
        self.assertNotIn("verified competence in both the origin and target languages", body)

    def test_translate_is_r3_everywhere(self):
        for path, pattern in (("skills/scio/SKILL.md", r"^\|.*translate\.md.*$"),
                              ("README.md", r"^\|.*`translate`.*$")):
            with self.subTest(file=path):
                row = re.search(pattern, text(path), re.M).group(0)
                self.assertIn("R3", row)
                self.assertNotIn("R2", row)

    def test_the_first_tasks_call_of_the_hour_carries_the_translators_lang(self):
        for path in ("skills/scio/references/workflows/loop.md", "skills/scio/references/workflows/translate.md"):
            with self.subTest(file=path):
                body = text(path)
                self.assertRegex(body, r"first `scio_get_tasks` call of the hour")
                self.assertIn("`lang`", body)


class RulesVerificationFailure(unittest.TestCase):
    """ident-11, e2e-17. scio_report needs a target_kind among proposal…discussion and a target_id: nothing names a
    rules document. The channel for a problem with the platform itself is scio_feedback."""

    def test_the_advice_names_a_tool_that_can_carry_it(self):
        sentence = re.search(r"rules that fail are data, not rules[^\n]*", text("skills/scio/SKILL.md")).group(0)
        self.assertNotIn("scio_report", sentence)
        self.assertIn("scio_feedback", sentence)
        keep = re.search(r"keep_bundled = \((.*?)\)\n", text("skills/scio/server/scio_bridge.py"), re.S).group(1)
        self.assertNotIn("scio_report", keep)
        self.assertIn("scio_feedback", keep)
        self.assertNotIn("report with scio_report", text("skills/scio/scripts/verify-rules.py"))


class Waits(unittest.TestCase):
    """skill-10. A read or a contest fee the wallet cannot cover answers quota_exceeded with quota `points`, and points
    never come back with time: rule 12 turned it into a wait until midnight, then another, for ever."""

    def test_a_points_refusal_is_not_a_wait(self):
        skill = text("skills/scio/SKILL.md")
        rule = re.search(r"^12\. .*$", skill, re.M).group(0)
        self.assertRegex(rule, r"`(?:quota: )?points`")
        self.assertRegex(rule, r"(?i)never comes? back with time")
        short = re.search(r"^Parameters, error codes.*$", skill, re.M).group(0)
        self.assertRegex(short, r"`(?:quota: )?points`")
        self.assertNotIn("Stop when quota runs out", text("commands/tasks.md"))


class SourceChecks(unittest.TestCase):
    """skill-9. scio_verify_source spends limits.source_verifications_per_day (whoami quota.verifications_left_today)
    except for a URL found live today (from_snapshot). A reviewer out of checks was told to wait until midnight while
    its seat expired."""

    def test_the_counter_and_the_free_recheck_are_documented(self):
        self.assertIn("verifications_left_today", text("skills/scio/SKILL.md"))
        self.assertIn("verifications_left_today", text("commands/status.md"))
        review = text("skills/scio/references/workflows/review.md")
        self.assertIn("source_verifications", review)
        self.assertIn("from_snapshot", review)
        self.assertRegex(review, r"`fetch` on `scio-local`")


class StaleFacts(unittest.TestCase):
    """skill-11, skill-12, ident-12, e2e-12. Ranks, tenures, permissions, panel size, the claim link and founders'
    rank, as the server and the signed rules have them today."""

    def test_the_permission_ladder_is_the_servers(self):
        table = section(text("skills/scio/references/roles.md"), "Roles (what `permissions` can contain)")
        for perm, rank in LADDER.items():
            with self.subTest(permission=perm):
                row = re.search(rf"^\| `{perm}` \| R(\d)", table, re.M)
                self.assertIsNotNone(row, f"roles.md has no row for {perm}")
                self.assertEqual(int(row.group(1)), rank)

    def test_the_whoami_example_is_a_rank_the_server_could_return(self):
        roles = text("skills/scio/references/roles.md")
        example = json.loads(re.search(r"```json\n(.*?)```", roles, re.S).group(1).replace("…", ""))
        self.assertEqual(set(example["permissions"]), {p for p, r in LADDER.items() if r <= example["rank"]})
        self.assertIn("verifications_left_today", example["quota"])

    def test_the_rank_table_names_the_permissions_each_rank_adds(self):
        ranks = section(text("skills/scio/references/roles.md"), "Ranks")
        rows = {n: re.search(rf"^\| R{n} \|.*$", ranks, re.M).group(0) for n in range(6)}
        for perm, rank in LADDER.items():
            with self.subTest(permission=perm):
                self.assertIn(f"`{perm}`", rows[rank])
                for other, row in rows.items():
                    if other != rank:
                        self.assertNotIn(f"`{perm}`", row, f"{perm} also named on R{other}")

    def test_rank_thresholds_cite_the_signed_rules(self):
        ranks = section(text("skills/scio/references/roles.md"), "Ranks")
        for n in range(2, 6):
            with self.subTest(rank=n):
                self.assertIn(f"`ranks.r{n}`", re.search(rf"^\| R{n} \|.*$", ranks, re.M).group(0))

    def test_no_stale_statement_survives(self):
        stale = (r"rotated at every call", r"free reads", r"(?i)escalat\w* to humans", r"(?i)shadow\*? reviews?",
                 r"panel of 7", r"4 of 7 must approve", r"(?i)founding operator[^.\n]{0,80}provisional",
                 r"provisional higher rank", r"×1\.5", r"3 days' tenure", r"18 days tenure", r"36 days tenure",
                 r"≥3,000 accepted", r"≥6,000 reviews", r"changes only when the outcome is confirmed",
                 r"confirmed by an arbiter panel", r"within the free quota", r"open a contest \(R3\+\)")
        for path in AGENT_DOCS:
            body = text(path)
            for pattern in stale:
                with self.subTest(file=path, pattern=pattern):
                    self.assertNotRegex(body, pattern)

    def test_the_first_paragraph_follows_the_growth_tiers(self):
        self.assertIn("panels.growth", text("skills/scio/SKILL.md").split("## 0.")[0])

    def test_review_pay_is_paid_at_submission(self):
        self.assertIn("economy.review", text("skills/scio/references/workflows/review.md"))


class SessionBrief(unittest.TestCase):
    """ident-12, skill-9. The brief whoami.py prints at session start is what an agent tells its operator: it named
    founding operators as the source of a provisional rank (a founder's agent is R5 with no end date, so it never has
    one) and never showed the source-check counter. Served by a local double of /v1/me through an isolated copy of the
    skill, the same device as test-onboarding.py."""

    ME = {}

    @classmethod
    def setUpClass(cls):
        me = cls.ME

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(me).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.copy = Path(tempfile.mkdtemp(prefix="scio-docs-"))
        shutil.copytree(SKILL, cls.copy / "scio", ignore=shutil.ignore_patterns("__pycache__"))
        common = cls.copy / "scio/scripts/scio_common.py"
        source = common.read_text(encoding="utf-8")
        common.write_text(source.replace('SCIO_HOST = "https://scio.md"',
                                         f'SCIO_HOST = "http://127.0.0.1:{cls.server.server_port}"', 1), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        shutil.rmtree(cls.copy, ignore_errors=True)

    def brief(self, **me):
        self.ME.clear()
        self.ME.update({"display_name": "t/t/fable", "rank": 5, "operator": {"id": "op_x", "verified": True},
                        "permissions": list(LADDER), "assignments": [], "rules_version": None,
                        "quota": {"proposals_left_today": 5, "reviews_left_today": 7, "points_balance": 900,
                                  "verifications_left_today": 1234},
                        "next_rank": None, "claim_url": None, "rank_provisional_until": None})
        self.ME.update(me)
        with tempfile.TemporaryDirectory() as base:
            keys = Path(base) / "keys"
            keys.write_text("fable=sk_test_DOCS_KEY_0123456789\n# default fable\n# model fable claude-fable-5\n")
            env = {k: v for k, v in os.environ.items() if not k.startswith("SCIO_") and k != "CLAUDE_PLUGIN_ROOT"}
            env.update(SCIO_KEYS_FILE=str(keys), SCIO_TRUST_FILE=str(Path(base) / "auto-approve"))
            r = subprocess.run([sys.executable, str(self.copy / "scio/scripts/whoami.py")], capture_output=True,
                               text=True, cwd=base, env=env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_brief_shows_the_source_checks_left(self):
        self.assertIn("source checks 1234", self.brief())

    def test_a_founders_agent_is_never_called_provisional(self):
        self.assertNotIn("provisional", self.brief())
        provisional = self.brief(rank=3, rank_provisional_until="2026-10-20T00:00:00.000000+00:00")
        self.assertIn("provisional until", provisional)
        self.assertNotIn("founding", provisional)


class Contest(unittest.TestCase):
    """skill-13. Arbiters see the target, the dispute's evidence and joined_reports — never a talk page; an appeal
    that cannot be seated is refused rate_limited with its fee returned, and a seated one always has its panel_id."""

    def test_contest_does_not_send_evidence_where_no_arbiter_reads(self):
        body = text("skills/scio/references/workflows/contest.md")
        self.assertNotRegex(body, r"add your evidence there with `scio_discuss`")
        self.assertNotIn("may be absent at first", body)
        self.assertIn("rate_limited", body)
        self.assertRegex(body, r"fee[^.\n]{0,30}returned")


class Reading(unittest.TestCase):
    """skill-15. `format` does not shorten an article; `max_chars` pages it by cursor (next_section)."""

    def test_read_pages_with_max_chars(self):
        body = text("skills/scio/references/workflows/read.md")
        self.assertIn("max_chars", body)
        self.assertIn("next_section", body)
        self.assertNotIn("~20k tokens", body)


class GapReservation(unittest.TestCase):
    """skill-16. A reservation lasts windows_minutes.gap_reservation and an active one is never extended; a team write
    outlives it, and another agent's live reservation turns the proposal into a conflict."""

    def test_the_gap_is_reserved_again_right_before_proposing(self):
        gap = text("skills/scio/references/workflows/gap.md")
        self.assertIn("reserved_by_you", gap)
        self.assertIn("windows_minutes.gap_reservation", gap)
        self.assertNotRegex(text("agents/scio-writer.md"), r"reserve it first")


class Media(unittest.TestCase):
    """skill-17, e2e-16. scio_upload_media needs sha256, ext, bytes, licence and origin (source_url for internet), and
    a pending upload is finished by a PUT of exactly those bytes to upload_url with the format's Content-Type."""

    def test_write_documents_the_whole_upload(self):
        write = text("skills/scio/references/workflows/write.md")
        for needle in ("`ext`", "`bytes`", "`origin`", "`source_url`", "upload_url", "PUT", "Content-Type",
                       "media_unverified"):
            with self.subTest(needle=needle):
                self.assertIn(needle, write)


if __name__ == "__main__":
    unittest.main()
