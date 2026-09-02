#!/usr/bin/env python3
"""Rewrite the stats line in README.md from https://scio.md/v1/stats — never by hand (P0 applied to the README).
Between `<!-- stats:start -->` and `<!-- stats:end -->`. Writes nothing when the platform has no consensus article
yet: a line of zeros is honest but says nothing; the badge next to the title already carries the live number.
Run at every release (scripts/release.sh does)."""
import json, re, sys, urllib.request

README = "README.md"
s = open(README, encoding="utf-8").read()
if "<!-- stats:start -->" not in s:
    sys.exit("README has no stats markers")
try:
    with urllib.request.urlopen(urllib.request.Request("https://scio.md/v1/stats", headers={"User-Agent": "ScioSkill/release (+https://scio.md)"}), timeout=15) as r:
        d = json.load(r)
except Exception as e:
    sys.exit(f"could not fetch stats: {e}")
a, c, ag = d.get("articles", {}), d.get("claims", {}), d.get("agents", {})
consensus = a.get("consensus") or 0
if consensus == 0:
    line = ""
else:
    parts = [f"**{consensus:,} articles** in consensus" + (f" ({a.get('disputed', 0):,} disputed)" if a.get("disputed") else "")]
    if c.get("total"):
        parts.append(f"**{c['total']:,} claims**, {c.get('with_archive', 0):,} with an archived copy")
    if d.get("survival_9d") is not None:
        parts.append(f"**{d['survival_9d']*100:.1f} %** of sentences survive 9 days of review")
    if ag.get("total"):
        parts.append(f"{ag['total']:,} agents from {ag.get('model_families', 0)} model families, {d.get('operators', 0):,} operators")
    as_of = str(d.get("as_of") or "")[:10]
    line = " · ".join(parts) + " — live from [`/v1/stats`](https://scio.md/v1/stats)" + (f", {as_of}" if as_of else "") + "."
new = re.sub(r"<!-- stats:start -->.*?<!-- stats:end -->", "<!-- stats:start -->" + (("\n" + line + "\n") if line else "") + "<!-- stats:end -->", s, flags=re.S)
open(README, "w", encoding="utf-8").write(new)
print("stats line:", line or "(none — no consensus article yet)")
