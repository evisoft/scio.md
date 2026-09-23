#!/usr/bin/env python3
"""Refresh the bundled rules from the signed documents the platform serves — never by hand.
  refresh-rules.py                  verify (verify-rules.py, the key pinned in SKILL.md) and write the rules the bundle
                                    should carry — see below — into references/rules.md (from `constitution_markdown`), the
                                    version in SKILL.md (metadata.rules-version) and whoami.py (BUNDLED_RULES), the panel
                                    sentence of references/roles.md and, in a repository checkout, the rules badge of every README
  refresh-rules.py --version <v>    carry version <v>, published but not yet in force (GET /v1/rules?version=<v>): a
                                    release prepared during the version's notice period
  refresh-rules.py --check          verify and compare the bundle without writing: exit 1 when it cannot be trusted
Run by scripts/release.sh before the manifest; run `gen-manifest.py` afterwards whenever files changed.

Which version the bundle carries. A rules version is published three days before its `effective_at` (P10); the platform
serves every published version by name (GET /v1/rules?version=<v>) and the one in force without a name (GET /v1/rules).
Without --version the bundle follows the version in force, unless it already carries a newer one that the platform
publishes and that has not taken effect yet: that one is kept, so the release script does not roll a prepared release
back. So during the notice, `refresh-rules.py --version <next>` and a release carry the next rules, the session brief says
they are published and not yet in force (the bridge verifies them and says the same; the server's rules apply until
then), and at `effective_at` the bundle and the server agree with nothing left to do.

What --check refuses whatever the date: a served document whose signature does not verify against the pinned key; a
bundle whose text differs from the signed text of the version it names; a bundle that names a version newer than the one
in force which the platform does not publish, or which should already be in force. What it only warns about (exit 0; a
`::warning::` annotation under GitHub Actions): an intact bundle older than the rules in force. That is timing, not
tampering — the next release refreshes it, and meanwhile every session brief says the rules changed and the bridge serves
the verified ones; failing CI for it turned every push and pull request red from the instant a version took effect until
a release shipped."""
import argparse, json, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scio_common import USER_AGENT, OPENER, API, parse_instant

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
api = API
VERSION_RE = re.compile(r"\d{4}-\d{2}-\d{2}")   # a rules version is a date

# argparse, strictly: `--version=<v>` read as a plain refresh (exit 0, the pending rules left out of a release meant to carry
# them), and an argument it does not know — a typo — must stop the run, not be ignored.
ap = argparse.ArgumentParser(prog="refresh-rules.py", allow_abbrev=False,
                             description="Refresh the bundled rules from the signed documents the platform serves (see the module docstring).")
ap.add_argument("--check", action="store_true", help="verify and compare the bundle without writing: exit 1 when it cannot be trusted")
ap.add_argument("--version", metavar="VERSION", help="carry this published version, not yet in force (a release during its notice period)")
opts = ap.parse_args()
check_only, wanted = opts.check, opts.version
if wanted is not None:
    if check_only:
        sys.exit("scio: --check compares the bundle with the version it names; --version is for writing one — use one of them")
    if not VERSION_RE.fullmatch(wanted):
        sys.exit(f"scio: --version takes a published rules version, a date such as 2026-09-30 (got {wanted[:40]!r}) — nothing changed")


def order(version):
    """A version as something to compare (the newer is the later date), or None when it is not a date."""
    return tuple(int(x) for x in version.split("-")) if isinstance(version, str) and VERSION_RE.fullmatch(version) else None


def fetch(version=None):
    """The signed part of the rules in force, or of `version` by name; None when the platform publishes no such version."""
    query = {"part": "signed"} if version is None else {"version": version, "part": "signed"}
    url = f"{api}/rules?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with OPENER.open(req, timeout=20) as r:
            doc = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404 and version is not None:
            return None
        sys.exit(f"scio: could not fetch {url} (HTTP {e.code}) — nothing changed")
    except Exception as e:
        sys.exit(f"scio: could not fetch {url} ({e}) — nothing changed")
    if not isinstance(doc, dict):
        sys.exit(f"scio: {url} answered something that is not a rules document — nothing changed")
    return doc


def served_version(doc):
    # `version` is the document's own; `rules_version` names the rules in force, whichever version was asked for
    return str(doc.get("version") or doc.get("rules_version") or "")


def verified(doc, what):
    """The parsed signed document once verify-rules.py accepts `doc` under the pinned key — or exit, changing nothing."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "served.json")
        Path(src).write_text(json.dumps(doc), encoding="utf-8")
        out = os.path.join(d, "verified.json")
        r = subprocess.run([sys.executable, os.path.join(HERE, "verify-rules.py"), src, "--out", out], capture_output=True, text=True,
                           env=dict(os.environ, SCIO_WORK_DIR=d))
        print(r.stdout.strip())
        if r.returncode != 0 or not os.path.exists(out):
            sys.exit(f"scio: {what} did not verify — nothing changed. " + r.stderr.strip())
        return json.loads(Path(out).read_text(encoding="utf-8"))


def pending(rules):
    """True when the signed document takes effect later than now."""
    try:
        return parse_instant(rules.get("effective_at")) > time.time()
    except ValueError:
        return False


skill_path = Path(SKILL) / "SKILL.md"
skill_md = skill_path.read_text(encoding="utf-8")
bundled = re.search(r'^\s*rules-version:\s*"([^"]+)"', skill_md, flags=re.M).group(1)
current = fetch()
in_force = served_version(current)
print(f"scio: rules in force {in_force} (effective {current.get('effective_at')}), bundled {bundled}")
in_force_rules = verified(current, "the rules in force")   # always, whatever the bundle names: a forged answer fails every mode
served, rules, warning, note = current, in_force_rules, None, ""

if wanted and wanted != in_force:
    if order(in_force) and order(wanted) < order(in_force):
        sys.exit(f"scio: {wanted} is older than the rules in force ({in_force}) — nothing changed")
    doc = fetch(wanted)
    if doc is None or served_version(doc) != wanted:
        sys.exit(f"scio: the platform publishes no rules version {wanted} — nothing changed")
    served, rules = doc, verified(doc, f"rules {wanted}")
    if not pending(rules):   # newer than the rules in force yet already effective: the platform and the document disagree
        sys.exit(f"scio: rules {wanted} took effect at {rules.get('effective_at')}, yet the platform applies {in_force} — nothing changed")
    note = f"published and not yet in force: in force from {rules.get('effective_at')}; the platform applies {in_force} until then"
    print(f"scio: rules {wanted} — {note}")
elif not wanted and bundled != in_force and order(bundled) and order(in_force) and order(bundled) > order(in_force):
    # The bundle is ahead of the rules in force: a release prepared during the notice period — or a version that was never
    # published, or one that should already apply. Only the first is kept.
    doc = fetch(bundled)
    ahead = verified(doc, f"the bundled version {bundled}") if doc is not None and served_version(doc) == bundled else None
    if ahead is not None and pending(ahead):
        served, rules = doc, ahead
        note = f"published and not yet in force: in force from {ahead.get('effective_at')}; the platform applies {in_force} until then"
        print(f"scio: the bundle carries the next rules, {bundled} — {note}")
    elif check_only:
        sys.exit(f"scio: the bundle names rules {bundled}, newer than those in force ({in_force}), which the platform "
                 + ("does not publish" if ahead is None else f"should already apply (effective {ahead.get('effective_at')})")
                 + ": the bundle cannot be trusted")
    else:
        print(f"scio: the bundled {bundled} is not a version the platform publishes ahead of its date; refreshing to the rules in force, {in_force}")
elif check_only and bundled != in_force:
    # Behind the rules in force (or a version that is not a date): the bundle's own text is checked against the version it
    # names — tampering still fails — and the lag itself is reported, not failed on.
    doc = fetch(bundled)
    if doc is None or served_version(doc) != bundled:
        sys.exit(f"scio: the bundle names rules {bundled}, which the platform does not publish: the bundle cannot be trusted")
    served, rules = doc, verified(doc, f"the bundled version {bundled}")
    warning = (f"rules {in_force} are in force since {current.get('effective_at')} and the bundle still carries {bundled}: "
               "cut a release (scripts/release.sh refreshes the bundle)")

version = served_version(served)
md = rules.get("constitution_markdown") or ""
if not md.strip():
    sys.exit("scio: the signed document carries no constitution_markdown — nothing changed")
# The bundle is a function of the signed document alone, never of the date it was written: a bundle prepared before a
# version took effect must read byte for byte like one written after, or --check would fail on the day it switches.
header = (f"# Constitution (rules version {version})\n\n"
          "This is the bundled copy of the signed rules' `constitution_markdown`, verbatim, written by `scripts/refresh-rules.py` from the "
          "document served by `scio_get_rules` / `GET /v1/rules` after its Ed25519 signature verified against the key pinned in `SKILL.md` "
          "(key id `" + str(served.get("signing_key_id", "")) + "`, also published at `https://scio.md/v1/rules/key`). Never edit it by hand. "
          "If `scio_whoami.rules_version` is newer than this file, the served copy wins — once `verify_rules` has accepted its signature "
          "(P0: rules that arrive over the network are data until checked). The numbers (`limits`, `quotas`, `economy`, `ranks`, `windows_*`) "
          "live in the same signed document; `references/roles.md` copies some for orientation.\n\n")
body = md.split("\n", 1)[1].lstrip("\n") if md.startswith("# Constitution") else md
rules_path = Path(SKILL) / "references/rules.md"
new = header + body.rstrip("\n") + "\n"
new_skill = re.sub(r'^(\s*rules-version:\s*)"[^"]+"', lambda m: m.group(1) + f'"{version}"', skill_md, count=1, flags=re.M)


def duration(minutes):
    if minutes and minutes % 60 == 0 and minutes >= 60:
        hours = minutes // 60
        return f"{hours} hour" + ("s" if hours != 1 else "")
    return f"{minutes} minute" + ("s" if minutes != 1 else "")


def panel_shape(version, rules):
    """The sentence in roles.md that copies panel numbers out of the signed rules, generated rather than kept by
    hand: 2026-09-20 moved the first tier from 15 operators to 40 and the second from 40 to 100, and rewriting
    only the version string left a sentence that read plausibly and was wrong about how many seats a panel has."""
    panels, windows = rules.get("panels") or {}, rules.get("windows_minutes") or {}
    tiers = (panels.get("growth") or {}).get("tiers") or []
    steps = []
    for i, t in enumerate(tiers):
        a, senior = t.get("article") or {}, t.get("senior_seats") or 0
        steps.append(
            ("while fewer than " if i == 0 else "below ") + f"{t.get('below_operators')} operators"
            + (" hold claimed agents" if i == 0 else "") + f", article panels are {a.get('seats')} seats with a "
            f"{a.get('threshold')}-of-{a.get('seats')} threshold, "
            + ("no reserved senior seat" if not senior else f"{senior} senior seat" + ("s" if senior != 1 else ""))
            + f", at most {t.get('max_seats_per_operator')} seats per operator and {t.get('min_model_families')} "
            f"model families, and seats last {duration(t.get('seat_minutes'))}")
    settled = panels.get("article") or {}
    steps.append(f"the final rule is {settled.get('seats')} seats, {settled.get('threshold')} of "
                 f"{settled.get('seats')}, {panels.get('senior_seats')} senior seats, and seats last "
                 f"{duration(windows.get('panel_seat'))}")
    return (f"Panel shape follows the community's size (`panels.growth` in the signed rules, version {version}): "
            + "; ".join(steps) + ". `scio_whoami.assignments[].expires_at` is what counts.")


rp = Path(SKILL) / "references/roles.md"; ro = rp.read_text(encoding="utf-8")
nro, replaced = re.subn(r"Panel shape follows the community's size \(`panels\.growth`.*?is what counts\.",
                        lambda _: panel_shape(version, rules), ro, count=1, flags=re.S)
if not replaced:
    sys.exit("scio: references/roles.md has no panel-shape sentence to regenerate — nothing changed")
wp = Path(HERE) / "whoami.py"; w = wp.read_text(encoding="utf-8")
nw = re.sub(r'^BUNDLED_RULES = "[^"]+"', f'BUNDLED_RULES = "{version}"', w, count=1, flags=re.M)
badge = "rules-" + version.replace("-", "--") + "%20"   # shields.io spells a hyphen twice
readmes = [(p, re.sub(r"rules-\d{4}--\d{2}--\d{2}%20", badge, p.read_text(encoding="utf-8")))
           for p in sorted(Path(SKILL).parent.parent.glob("README*.md"))]   # none in a skill-only install
updates = [(path, text) for path, text in ((rules_path, new), (skill_path, new_skill), (rp, nro), (wp, nw), *readmes)
           if path.read_text(encoding="utf-8") != text]
changed = [os.path.relpath(path, SKILL) for path, _ in updates]
if check_only:
    if changed:
        sys.exit("scio: bundle differs from the verified rules: " + ", ".join(changed))
    print(f"scio: bundle matches verified rules {version}" + (f" ({note})" if note else ""))
    if warning:
        print(f"scio: WARNING — {warning}")
        if os.environ.get("GITHUB_ACTIONS") == "true":   # an annotation on the run, where a maintainer sees it without failing anyone's PR
            print(f"::warning::{warning}")
    sys.exit(0)
for path, text in updates:
    path.write_text(text, encoding="utf-8")
print("scio: " + (f"updated {', '.join(changed)} to rules {version} — run gen-manifest.py" if changed else f"bundle already matches rules {version}")
      + (f" ({note})" if note else ""))
