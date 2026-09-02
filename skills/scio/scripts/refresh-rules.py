#!/usr/bin/env python3
"""Refresh the bundled rules from the live signed document — never by hand.
  refresh-rules.py            fetch GET /v1/rules (anonymous), verify the Ed25519 signature against the pinned key
                              (verify-rules.py), then rewrite references/rules.md from `constitution_markdown` and set
                              the version in SKILL.md (metadata.rules-version) and whoami.py (BUNDLED_RULES)
  refresh-rules.py --check    only report whether the bundle matches the served version (exit 1 when it does not)
Run by scripts/release.sh before the manifest; run `gen-manifest.py` afterwards whenever files changed."""
import json, os, re, subprocess, sys, tempfile, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scio_common import USER_AGENT, OPENER, API

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
api = API
check_only = "--check" in sys.argv

req = urllib.request.Request(f"{api}/rules", headers={"User-Agent": USER_AGENT})
try:
    with OPENER.open(req, timeout=20) as r:
        served = json.load(r)
except Exception as e:
    sys.exit(f"scio: could not fetch {api}/rules ({e})")

skill_md = open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8").read()
bundled = re.search(r'^\s*rules-version:\s*"([^"]+)"', skill_md, flags=re.M).group(1)
version = served.get("version") or served.get("rules_version")
print(f"scio: served rules {version} (effective {served.get('effective_at')}), bundled {bundled}")
if check_only:
    sys.exit(0 if version == bundled else 1)

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "served.json")
    json.dump(served, open(src, "w"))
    out = os.path.join(d, "verified.json")
    r = subprocess.run([sys.executable, os.path.join(HERE, "verify-rules.py"), src, "--out", out], capture_output=True, text=True,
                       env=dict(os.environ, SCIO_WORK_DIR=d))
    print(r.stdout.strip())
    if r.returncode != 0 or not os.path.exists(out):
        sys.exit("scio: the served rules did not verify — nothing changed. " + r.stderr.strip())
    rules = json.load(open(out))

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
rules_path = os.path.join(SKILL, "references", "rules.md")
new = header + body.rstrip("\n") + "\n"
changed = []
if open(rules_path, encoding="utf-8").read() != new:
    open(rules_path, "w", encoding="utf-8").write(new); changed.append("references/rules.md")
new_skill = re.sub(r'^(\s*rules-version:\s*)"[^"]+"', lambda m: m.group(1) + f'"{version}"', skill_md, count=1, flags=re.M)
if new_skill != skill_md:
    open(os.path.join(SKILL, "SKILL.md"), "w", encoding="utf-8").write(new_skill); changed.append("SKILL.md")
rp = os.path.join(SKILL, "references", "roles.md"); ro = open(rp, encoding="utf-8").read()
nro = re.sub(r"(`panels\.growth` in the signed rules, version )\d{4}-\d{2}-\d{2}", lambda m: m.group(1) + version, ro, count=1)
if nro != ro:
    open(rp, "w", encoding="utf-8").write(nro); changed.append("references/roles.md")
wp = os.path.join(HERE, "whoami.py"); w = open(wp, encoding="utf-8").read()
nw = re.sub(r'^BUNDLED_RULES = "[^"]+"', f'BUNDLED_RULES = "{version}"', w, count=1, flags=re.M)
if nw != w:
    open(wp, "w", encoding="utf-8").write(nw); changed.append("scripts/whoami.py")
print("scio: " + (f"updated {', '.join(changed)} to rules {version} — run gen-manifest.py" if changed else f"bundle already matches rules {version}"))
