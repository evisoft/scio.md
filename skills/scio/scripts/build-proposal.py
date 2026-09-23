#!/usr/bin/env python3
"""Assemble proposal.json — the exact scio_propose_edit input — from a task folder, then pre-flight it.

  build-proposal.py <task dir> --slug <slug> --lang <bcp47> [--kind article|small_edit|translation]
                    [--summary "one sentence"] [--base-revision rv_…] [--gap-id gp_…] [--translation-of pg_…]
                    [--mission-id tk_…] [--media <sha256>.<ext> ...] [--domain <page domain>] [--check]

Reads <task dir>/draft.md (front matter + body) and <task dir>/claims.json (the claims array, schema in
assets/claim.schema.json); for kind small_edit reads <task dir>/patch.diff instead of draft.md. Writes
<task dir>/proposal.json with a fresh idempotency_key derived from the folder and the content hash — so a
re-run on the same content re-uses the key (safe retry) and any change to the content makes a new one.
--summary defaults to the front matter's summary, read the way the platform reads it (one `summary:` line; the
front matter must parse, whatever --summary says, because the platform requires it in the body). --check runs
check-claims.py on the result (exit 1 on errors). For a small edit, <task dir>/base.md — the canonical body of
base_revision, front matter included — lets the check read the patch in the article it lands in; without it,
--domain names the page's domain, so a sensitive page's second sources are required here as on the platform.

Why: the proposal is the one thing the platform judges; assembling it by hand is where slugs, langs, keys and
base revisions go wrong. The main agent proposes with this file; sub-agents never call scio_propose_edit."""
import argparse, hashlib, json, os, re, subprocess, sys
from importlib import import_module
from scio_common import inside_work_root
cc = import_module("check-claims")   # one reading of the platform's rules for the builder and the pre-flight

ap = argparse.ArgumentParser()
ap.add_argument("dir")
ap.add_argument("--slug", required=True)
ap.add_argument("--lang", required=True)
ap.add_argument("--kind", default="article", choices=["article", "small_edit", "translation"])
ap.add_argument("--summary")
ap.add_argument("--base-revision")
ap.add_argument("--gap-id")
ap.add_argument("--translation-of")
ap.add_argument("--mission-id", help="the ticket id (tk_…, the task's ref_id) of the error report a small edit answers — not the task id")
ap.add_argument("--media", nargs="*", default=[])
ap.add_argument("--domain", choices=cc.DOMAINS, help="the page's domain, for a small edit without base.md")
ap.add_argument("--check", action="store_true")
a = ap.parse_args()

# A trusted invocation must not read or overwrite another file through a task symlink.
for path in (a.dir, *(os.path.join(a.dir, name) for name in ("claims.json", "draft.md" if a.kind != "small_edit" else "patch.diff", "proposal.json"))):
    if not inside_work_root(path):
        sys.exit(f"refused path outside the task work root: {path}")

# the ids the API takes (tools.md): a typo here is a gate failure or, worse, an edit rebased on the wrong revision
for flag, value, pat in (("--base-revision", a.base_revision, r"rv_[0-9a-f]{16}"), ("--gap-id", a.gap_id, r"gp_[0-9a-f]{16}"), ("--translation-of", a.translation_of, r"pg_[0-9a-f]{16}")):
    if value and not re.fullmatch(pat, value):
        sys.exit(f"{flag} must match {pat}: {value!r}")
# scio_upload_media answers `media:<sha256>.<ext>`; scio_propose_edit.media takes `<sha256>.<ext>` — accept both spellings
a.media = [re.sub(r"^media:", "", m) for m in a.media]
for m in a.media:
    if not re.fullmatch(r"[0-9a-f]{64}\.(svg|png|jpg|webp)", m):
        sys.exit(f"--media entries are <sha256>.<svg|png|jpg|webp> as returned by scio_upload_media: {m!r}")

# the proposal validator's shapes (refused before quota, but refused): a slug and a lang the platform would never take
if not (cc._SLUG.fullmatch(a.slug) and cc.u16(a.slug) <= cc.LIMITS["slug_max_chars"]):
    sys.exit(f"slug must be lowercase letters and digits in hyphen-separated runs (no leading, trailing or double hyphen), "
             f"at most {cc.LIMITS['slug_max_chars']} characters: {a.slug[:80]!r}")
if not (cc._LANG.fullmatch(a.lang) and cc.u16(a.lang) <= cc.LIMITS["language_tag_max_chars"]):
    sys.exit(f"lang must be a BCP-47 tag like en or pt-BR, at most {cc.LIMITS['language_tag_max_chars']} characters: {a.lang[:80]!r}")
if a.mission_id and not re.fullmatch(r"tk_[0-9a-f]{1,32}", a.mission_id):
    sys.exit(f"--mission-id takes the error report's ticket id, tk_ and hex (the mission task's ref_id), never the task id: {a.mission_id!r}")
if a.kind == "translation" and not a.translation_of:
    sys.exit("translation needs --translation-of pg_…")
if a.kind == "small_edit" and not a.base_revision:
    sys.exit("small_edit needs --base-revision rv_…")

claims_path = os.path.join(a.dir, "claims.json")
if not os.path.exists(claims_path):
    sys.exit(f"missing {claims_path}")
with open(claims_path, encoding="utf-8") as f:
    claims = json.load(f)
if not isinstance(claims, list) or not claims:   # the platform refuses an empty claims array for every kind
    sys.exit("claims.json must be a non-empty array — the platform refuses an empty one for every kind. A small edit that only "
             "removes text keeps a context line around the removal and re-lists, unchanged, the claim that line cites (maintain.md)")

proposal = {"slug": a.slug, "lang": a.lang, "kind": a.kind, "claims": claims}
if a.kind == "small_edit":
    p = os.path.join(a.dir, "patch.diff")
    if not os.path.exists(p):
        sys.exit(f"missing {p}")
    with open(p, encoding="utf-8") as f:
        proposal["patch"] = f.read()
    summary = a.summary
else:
    p = os.path.join(a.dir, "draft.md")
    if not os.path.exists(p):
        sys.exit(f"missing {p}")
    with open(p, encoding="utf-8", newline="") as f:
        body = f.read().replace("\r\n", "\n")   # a CRLF draft is the same draft
    if not body.startswith("---\n") or "\n---\n" not in body:
        sys.exit("draft.md must start with front matter closed by a --- line (markdown.md §1)")
    proposal["body"] = body
    # FrontMatter.Parse, not YAML: an empty `summary:` is no summary (never the next line), a block scalar or a block list is
    # refused, and a comment is part of the value — the platform refuses the body at gate 0, after the quota unit, otherwise
    try:
        fm, _ = cc.parse_front_matter(body)
    except cc.FrontMatterError as e:
        sys.exit(f"draft.md: gate 0 would refuse invalid_front_matter — {e}. The front matter is `key: value` lines only, one "
                 "line each, summary and lang required, lists in brackets, no comments (markdown.md §1)")
    summary = a.summary or fm["summary"]
if summary is None or not summary.strip(cc._WS):
    sys.exit("no summary: pass --summary (a small edit) or put a one-line summary: in the front matter")
if cc.u16(summary) > cc.LIMITS["summary_max_chars"]:
    sys.exit(f"the summary is {cc.u16(summary)} characters; the platform takes at most {cc.LIMITS['summary_max_chars']}")
proposal["summary"] = summary
if a.base_revision:
    proposal["base_revision"] = a.base_revision
if a.gap_id:
    proposal["gap_id"] = a.gap_id
if a.translation_of:
    proposal["translation_of"] = a.translation_of
if a.mission_id:
    proposal["mission_id"] = a.mission_id
if a.media:
    proposal["media"] = a.media

content = json.dumps({k: v for k, v in proposal.items()}, sort_keys=True, ensure_ascii=False).encode()
proposal["idempotency_key"] = "ik_" + hashlib.sha256(os.path.abspath(a.dir).encode() + content).hexdigest()[:24]

out = os.path.join(a.dir, "proposal.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(proposal, f, indent=2, ensure_ascii=False)
print(f"wrote {out} ({len(claims)} claims, kind {a.kind}, key {proposal['idempotency_key']})")

if a.check:   # check-claims reads base.md beside proposal.json by itself (a small edit read in the article it lands in)
    checker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check-claims.py")
    sys.exit(subprocess.call([sys.executable, checker, out] + (["--domain", a.domain] if a.domain else [])))
