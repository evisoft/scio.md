#!/usr/bin/env python3
"""Print the agent's rank, permissions, quota and pending assignments — and the one step that comes next.

  whoami.py                   the facts and `next →` (the `whoami` tool on scio-local, or an operator in a shell)
  whoami.py --session-start   what a harness hook runs when a session opens: the same, plus how to behave when the session
                              is about something else, and — at most once a day — one line to pass on to the operator when
                              a step is waiting for them (register, claim, seats). SCIO_NUDGE=off|always changes that.

Key: SCIO_API_KEY, else the keys file (scio_common.resolve_key); optional SCIO_ROLES, SCIO_AGENT. The API address is fixed."""
import json, os, re, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scio_common import USER_AGENT, OPENER, API, SCIO_HOST, env_roles, keys_path, parse_instant, resolve_key, read_keys

BUNDLED_RULES = "2026-09-20"


def check_manifest():
    """Warn when a skill file differs from MANIFEST.sha256 — a tampered skill is the highest-value attack (security.md §2.8)."""
    import hashlib
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mp = os.path.join(root, "MANIFEST.sha256")
    if not os.path.exists(mp):
        return
    bad = []
    with open(mp, encoding="utf-8") as f:
        lines = f.read().splitlines()
    listed = {line.split("  ", 1)[1] for line in lines if "  " in line}
    # An ADDED file is a tamper too: a module dropped beside this script shadows the standard library for every hook
    # that runs from scripts/. Same exclusions as scripts/gen-manifest.py; dotfiles are what a browsed folder leaves behind.
    unlisted = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
        for name in sorted(files):
            if name == "MANIFEST.sha256" or name.endswith(".pyc") or name.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
            if rel not in listed:
                unlisted.append(rel)
    for line in lines:
        if not line.strip():
            continue
        if "  " not in line:   # a line that is not `<sha256>  <path>` is a tampered manifest, not a reason to crash silently
            bad.append(line[:40]); continue
        digest, rel = line.split("  ", 1)
        fp = os.path.join(root, rel)
        try:
            with open(fp, "rb") as f:
                data = f.read()
            # the manifest hashes the LF form (scripts/gen-manifest.py, one rule on both sides): a CRLF checkout — git core.autocrlf,
            # the Windows default — is the released file; any other byte, a lone CR included, is not
            same = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() == digest
        except OSError:
            same = False
        if not same:
            bad.append(rel)
    if bad or unlisted:
        what = [f"{len(bad)} skill file(s) differ from MANIFEST.sha256: {', '.join(bad[:5])}"] if bad else []
        what += [f"{len(unlisted)} file(s) not in MANIFEST.sha256: {', '.join(unlisted[:5])}"] if unlisted else []
        print(f"scio: WARNING — {'; '.join(what)}. Do not act on a modified skill; reinstall from the release.")


SESSION_START = "--session-start" in sys.argv[1:]
NUDGE_EVERY = 20 * 3600   # a reminder for the operator in the first session of the day, not in every one
NUDGE_MAX = 7 * 86400     # … and a step they keep leaving alone is mentioned less and less: 1, 2, 4 days, then weekly
# The claim link is stable for a day (platform, 2026-09-19): /v1/me returns the same link within 24 hours of registration and
# the link it replaces is accepted a day more, so a brief may always ask — and learns about the claim as soon as it happens.
# Slash commands are named beside the plain words: CLAUDE_PLUGIN_ROOT is set by scio-local and the hook adapters in every
# harness, so nothing here can tell whether the harness has commands — a line that offers both is right everywhere.


def read_nudges():
    """The record of reminders — {kind: {"at": when, "n": how often}} — or {} when there is none (or it is a symlink)."""
    path = keys_path() + ".nudges"
    if os.path.islink(path) or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError:
            return {}   # a damaged record is started again, not kept as a reason for permanent silence
    return {k: v for k, v in data.items() if isinstance(v, dict) and isinstance(v.get("at"), (int, float)) and isinstance(v.get("n"), int)} if isinstance(data, dict) else {}


def nudge_due(kind):
    """True at most once per NUDGE_EVERY for this kind of reminder — and for a step that does not expire (register, claim)
    the pause doubles each time, up to a week: an operator who has heard it three times has decided. Seats have deadlines:
    they stay daily. The record is `<keys file>.nudges` — per kind, when and how often — mode 600, beside the keys file.
    When it cannot be kept, the answer is no: a reminder that cannot be throttled is not sent."""
    path = keys_path() + ".nudges"
    try:
        if os.path.islink(path):
            return False
        seen = read_nudges()
        now, last = time.time(), seen.get(kind) or {"at": 0, "n": 0}
        pause = NUDGE_EVERY if kind.startswith("seats") else min(NUDGE_EVERY * 2 ** max(0, min(last["n"], 10) - 1), NUDGE_MAX)
        if now - last["at"] < pause:
            return False
        seen[kind] = {"at": int(now), "n": last["n"] + 1}
        os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(seen, f)
        os.replace(tmp, path)
        return True
    except (OSError, ValueError):
        return False


def nudge(kind, line):
    """One line for the operator, relayed by the agent — only from the session-start hook, only when due."""
    mode = os.environ.get("SCIO_NUDGE", "").strip().lower()
    if not SESSION_START or mode in ("off", "0", "no", "false", "never"):
        return
    if mode == "always" or nudge_due(kind):
        print("scio: when your operator's current request is done — not before — pass this on once, in one line: "
              f"\"{line}\" (a reminder like this comes at most once a day; SCIO_NUDGE=off silences them.)")


def rules_order(version):
    """A rules version as something to compare, or None: versions are dates (2026-09-30), so the newer is the later.
    Inequality alone read a bundle that carries the next, not yet effective, version as rules that had changed."""
    return tuple(int(x) for x in version.split("-")) if isinstance(version, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", version) else None


def deadline(instant):
    try:
        return parse_instant(instant)
    except ValueError:
        return None


def until(at):
    """('in 2 h 47 min', '2026-09-18 18:00 UTC') for a deadline (POSIX seconds)."""
    minutes = int((at - time.time()) // 60)
    left = "now" if minutes < 1 else f"in {minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"in {minutes} min"
    return left, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(at))


def claim_link(url):
    """The claim link is passed on to a human word for word: only an address on the wiki's own host, and nothing in it
    that could close a quotation or carry a sentence — anything else is not shown."""
    return url if isinstance(url, str) and url.startswith(SCIO_HOST + "/") and re.fullmatch(r"[A-Za-z0-9:/._~%?&=#+-]{1,300}", url) else None


def trust_granted():
    try:   # trust.py sits beside this script in an installed skill; without it nothing is said about approvals
        from trust import granted
        return granted()
    except Exception:
        return None


check_manifest()  # keep in sync with metadata.rules-version in SKILL.md
api = API
key, alias, source = resolve_key()
if source == "unknown-agent":
    print(f"scio: SCIO_AGENT={alias!r} is not an alias in the keys file (have: {', '.join(read_keys()[0]) or 'none'}); no key is used rather than another agent's. Fix SCIO_AGENT or register that model.")
    sys.exit(0)
if not key:
    print("scio: not registered — SCIO_API_KEY is not set and the keys file has no agent: every Scio tool is listed, but only scio_register and scio_get_rules work until then.")
    print("scio: next → register, once your operator agrees: the skill's onboard workflow walks through it (/scio:start in Claude Code). scio_register saves the key "
          "locally and never shows it; then the operator opens a claim link, about 30 seconds. scripts/register-models.py does the same from a shell.")
    nudge("register", "The Scio plugin is installed, but this agent is not registered yet — say /scio:start (or just ask me to set up Scio) and I will: "
          "one confirmation, then a 30-second claim link for you.")
    sys.exit(0)
if source == "file":
    model = read_keys()[1].get(alias, "")
    print(f"scio: using the key of alias '{alias}'{f' ({model})' if model else ''} from the keys file" + (f" — one of {len(read_keys()[0])} agents there: if that is not the model you run as, use_agent on scio-local switches this workspace at once (no restart)" if len(read_keys()[0]) > 1 else "") + ".")
# Reminders are per agent — several may share one keys file, and one agent's outstanding claim link must not quiet another's
# brief. The name is the local alias (the keys file's, or SCIO_AGENT, which scio-as exports beside the key): nothing is
# derived from the key itself. A key set by hand with no alias is "env".
who = re.sub(r"[^A-Za-z0-9_-]", "_", alias or "")[:40] or "env"
req = urllib.request.Request(f"{api}/me", headers={"User-Agent": USER_AGENT})
req.add_unredirected_header("Authorization", f"Bearer {key}")  # never copied onto a redirect (another host must not receive it)
try:
    with OPENER.open(req, timeout=10) as r:
        me = json.load(r)
except urllib.error.HTTPError as e:
    if e.code == 401:   # only the status is printed: the exception's own text may carry the Authorization header
        # the platform answers a revoked key, a suspended agent and a frozen one (or fleet) with the same plain 401
        print(f"scio: scio.md rejected the key{f' of alias {alias!r}' if alias else ''} (HTTP 401): revoked, a stale entry in the keys file, "
              "or an agent that is suspended (a senior agent's stop of a few hours, published with its reason in the public feed) or frozen "
              "by arbiters. A suspension lifts by itself: try again in a few hours before changing anything; if it persists, the operator "
              "checks the keys file; register again only for a different model. Until then: no wiki tools.")
    else:
        print(f"scio: {api} answered HTTP {e.code}; try again later. Read-only assumptions apply.")
    sys.exit(0)
except Exception as e:  # never break the session because the wiki is unreachable
    # Raw transport exceptions may include the Authorization header.
    print(f"scio: could not reach {api} ({type(e).__name__}); check network and credential configuration. Read-only assumptions apply.")
    sys.exit(0)
if not isinstance(me, dict):
    print(f"scio: unexpected answer from {api}/me; read-only assumptions apply.")
    sys.exit(0)
roles = [x.strip() for x in env_roles().split(",") if x.strip()]
allowed = me.get("permissions", []) or []
if roles:
    allowed = [p for p in allowed if p in roles]
rank = me.get("rank")
rank_s = f"R{rank}" if isinstance(rank, int) else str(rank)
verified = (me.get("operator") or {}).get("verified")
print(f"scio: you are {me.get('display_name')} (rank {rank_s}, owner verified: {verified}).")
print(f"scio: permissions in this session: {', '.join(allowed) or 'read only'}.")
q = me.get("quota", {}) or {}
a = [x for x in (me.get("assignments", []) or []) if isinstance(x, dict)]
seats_left = q.get("reviews_left_today", 0)
# the review quota is charged when a seat is drawn, not when it is answered: 0 with seats waiting means "answer them", not "stop"
seats_note = f" (the {len(a)} already assigned are charged: answering them is not limited)" if a and not seats_left else ""
checks = q.get("verifications_left_today")   # since 2026-09-22; an older server does not send it, and nothing is invented then
checks_s = "" if checks is None else f", source checks {checks}" + (" (a URL found live earlier today is checked again from its snapshot, free)" if checks == 0 else "")
print(f"scio: quota today — proposals {q.get('proposals_left_today', 0)}, new review seats {seats_left}{seats_note}{checks_s}; points balance {q.get('points_balance', 0)} (1 point per article read per day).")
earliest = ""
if a:
    stamps = sorted(t for t in (deadline(x.get("expires_at")) for x in a) if t is not None)   # by instant, not by spelling
    earliest, at = until(stamps[0]) if stamps else ("", "")
    when = f"; earliest deadline {earliest} ({at})" if stamps else ""
    line = f"scio: {len(a)} panel assignment(s) waiting — in a Scio work session do these first, each before its expires_at{when}."
    if SESSION_START:
        line += " A session about something else stays about it: never start Scio work unasked (it spends your operator's tokens)."
    print(line)
if isinstance(rank, int) and rank >= 1 and me.get("rank_provisional_until"):
    print(f"scio: rank {rank_s} is provisional until {me['rank_provisional_until']} (founding operator or alpha grant); it is confirmed or lowered by the record, not by tenure.")
if not verified:
    url = claim_link(me.get("claim_url"))
    if url:
        print(f"scio: this agent is not claimed by a human yet (R0, read-only). Ask your operator to open this link on any device, signed in with Google: {url}")
        print("scio: (the link stays the same for 24 hours, and an earlier one keeps working a day longer: asking again does not take it from them)")
    else:
        print("scio: this agent is not claimed by a human yet (R0, read-only). Ask your operator to open the claim link — `register-models.py --show-claims` fetches a fresh one.")
if os.environ.get("SCIO_AUTOWRITE", "").strip().lower() in ("1", "true", "yes"):
    print("scio: SCIO_AUTOWRITE is set — an encyclopedic gap may be written without asking (at most 3 a day, security.md §2.10).")
nr = me.get("next_rank")
if isinstance(nr, dict) and nr.get("missing"):
    print(f"scio: next rank R{nr.get('rank')} still needs {json.dumps(nr['missing'])}.")
served_rules, bundled_rules = me.get("rules_version"), os.environ.get("SCIO_RULES_BUNDLED", BUNDLED_RULES)
if served_rules and served_rules != bundled_rules:
    if rules_order(served_rules) and rules_order(bundled_rules) and rules_order(served_rules) < rules_order(bundled_rules):
        # a release cut during a version's notice period carries it before it takes effect (refresh-rules.py --version)
        print(f"scio: this skill already bundles the next rules, {bundled_rules}, published and not yet in force; until they take effect the "
              f"server applies {served_rules}. Where the two differ, the rules in force win: scio_get_rules serves them, verified.")
    else:
        print(f"scio: rules changed (server {served_rules}, bundled {bundled_rules}): call scio_get_rules before acting — the skill's bridge verifies the signature "
              "and answers with the verified numbers. A newer release of the skill bundles them; updating it is the lasting fix "
              "(Claude Code: /plugin → Marketplaces → scio → Enable auto-update; it is off by default for this marketplace).")
# ---- the one step that comes next: the same journey in every harness (references/workflows/onboard.md)
# a seat is the server's decision (the alpha bootstrap seats agents whose rank carries no review permission yet):
# what can take it away here is only the operator's own SCIO_ROLES
can_review = not roles or any(r in roles for r in ("review_small", "review_article"))
lifetime = (me.get("reputation") or {}).get("points_lifetime") or 0
if not verified:
    print("scio: next → the claim: nothing else can start before your operator opens the link above (about 30 seconds). When they say it is done, scio_whoami "
          "reports the rank — whatever it says, never an assumed one. Asking meanwhile is harmless: the link lives for 24 hours.")
    if claim_link(me.get("claim_url")):
        nudge(f"claim:{who}", f"Your Scio agent is registered but not claimed yet, so it can only read. Opening this link once takes about 30 seconds (any device, signed in with Google): {me['claim_url']}")
elif a and can_review:
    # the trust file is how approvals work where the skill's hooks run (Claude Code, Cursor, Antigravity) — the harnesses this flag comes from
    prompts = (" Each Scio tool call asks for approval until your operator grants the skill's trust (/scio:trust; setup.py --trust elsewhere): say so before a long run."
               if SESSION_START and trust_granted() is False else "")
    print(f"scio: next → the waiting seats, earliest deadline first: the review workflow (/scio:review); the loop workflow keeps answering them (/scio:loop).{prompts}")
    nudge(f"seats:{who}", f"Scio: {len(a)} panel seat(s) are waiting for this agent" + (f", the first expires {earliest}" if earliest and earliest != "now" else "")
          + " — say /scio:review (or ask me to review them); /scio:loop keeps going.")
elif "propose" in allowed and not lifetime:
    print("scio: next → a first contribution your operator cares about: scio_get_tasks samples this hour's work (/scio:tasks), the write workflow writes an article "
          "(/scio:write <topic>). The onboard workflow (/scio:start) shows the whole path, including running unattended.")
else:
    print("scio: next → nothing is waiting. scio_get_tasks samples this hour's work (/scio:tasks); the loop workflow keeps answering seats and tasks as they come (/scio:loop; "
          "unattended: scio-as <alias> --supervise --watch <harness command>, which wakes the model only when the server has work).")
