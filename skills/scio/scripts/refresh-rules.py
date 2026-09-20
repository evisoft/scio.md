#!/usr/bin/env python3
"""Refresh the bundled rules from the live signed document — never by hand.
  refresh-rules.py            fetch GET /v1/rules (anonymous), verify the Ed25519 signature against the pinned key
                              (verify-rules.py), then rewrite references/rules.md from `constitution_markdown` and set
                              the version in SKILL.md (metadata.rules-version), whoami.py (BUNDLED_RULES) and, in a
                              repository checkout, the rules badge of every README
  refresh-rules.py --check    verify the signature and compare the bundle without writing (exit 1 on mismatch)
Run by scripts/release.sh before the manifest; run `gen-manifest.py` afterwards whenever files changed."""
import json, os, re, subprocess, sys, tempfile, urllib.request
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scio_common import USER_AGENT, OPENER, API

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
api = API
check_only = "--check" in sys.argv

req = urllib.request.Request(f"{api}/rules?part=signed", headers={"User-Agent": USER_AGENT})
try:
    with OPENER.open(req, timeout=20) as r:
        served = json.load(r)
except Exception as e:
    sys.exit(f"scio: could not fetch {api}/rules ({e})")

skill_path = Path(SKILL) / "SKILL.md"
skill_md = skill_path.read_text(encoding="utf-8")
bundled = re.search(r'^\s*rules-version:\s*"([^"]+)"', skill_md, flags=re.M).group(1)
version = served.get("version") or served.get("rules_version")
print(f"scio: served rules {version} (effective {served.get('effective_at')}), bundled {bundled}")

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "served.json")
    Path(src).write_text(json.dumps(served), encoding="utf-8")
    out = os.path.join(d, "verified.json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "verify-rules.py"), src, "--out", out], capture_output=True, text=True,
                       env=dict(os.environ, SCIO_WORK_DIR=d))
    print(r.stdout.strip())
    if r.returncode != 0 or not os.path.exists(out):
        sys.exit("scio: the served rules did not verify — nothing changed. " + r.stderr.strip())
    rules = json.loads(Path(out).read_text(encoding="utf-8"))

md = rules.get("constitution_markdown") or ""
if not md.strip():
    sys.exit("scio: the signed document carries no constitution_markdown — nothing changed")
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


def panel_shape(version):
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
                        lambda _: panel_shape(version), ro, count=1, flags=re.S)
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
    print(f"scio: bundle matches verified rules {version}")
    sys.exit(0)
for path, text in updates:
    path.write_text(text, encoding="utf-8")
print("scio: " + (f"updated {', '.join(changed)} to rules {version} — run gen-manifest.py" if changed else f"bundle already matches rules {version}"))
