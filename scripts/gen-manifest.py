#!/usr/bin/env python3
"""Write skills/scio/MANIFEST.sha256 — the SHA-256 of every file in the skill (except the manifest itself).
Lives in the repository's scripts/, not in the skill: it is a release tool, not something an installed agent runs.
Run by the maintainer before a release (scripts/release.sh does); whoami.py verifies the installed skill against it at session start and
warns when a file differs (beyond CRLF line endings, which a Windows checkout produces). The skill is the agents' shared brain: a modified SKILL.md or workflow is the highest-value
attack there is, and a checksum is the cheapest thing that makes it visible. The manifest is committed with the
release, and release.sh prints the manifest's own hash in the GitHub release notes so an installed copy can be checked end to end.
The skill ships text files only: the hashes are of the LF form (a CRLF checkout must yield this same manifest), and a file
with a lone CR or a NUL byte could not be hashed that way and verified with `sha256sum -c` alike, so it is refused."""
import hashlib, os, sys

root = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else \
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "scio")   # the installable tree, nothing else; tests pass a copy
if len(sys.argv) > 2 or not os.path.isfile(os.path.join(root, "SKILL.md")):
    print(f"usage: gen-manifest.py [<skill dir>]   -- {root} has no SKILL.md, so it is not a skill; nothing written", file=sys.stderr); sys.exit(2)
lines = []
refused = []
for dirpath, dirs, files in os.walk(root):
    dirs[:] = sorted(d for d in dirs if d != "__pycache__")
    for f in sorted(files):
        if f == "MANIFEST.sha256" or f.endswith(".pyc"):
            continue
        p = os.path.join(dirpath, f)
        rel = os.path.relpath(p, root).replace(os.sep, "/")   # forward slashes, so a Windows checkout writes the same paths
        with open(p, "rb") as fh:
            data = fh.read().replace(b"\r\n", b"\n")   # hash the LF form: the one rule shared with whoami.py, so a CRLF checkout (git core.autocrlf, the Windows default) yields the release's manifest
        if b"\r" in data or b"\0" in data:
            refused.append(rel); continue
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
if refused:
    sys.exit(f"ERROR: not text with LF (or CRLF) line endings, so the LF-form hash and sha256sum -c would disagree: {', '.join(refused)}; nothing written")
out = os.path.join(root, "MANIFEST.sha256")
with open(out, "w", encoding="utf-8", newline="\n") as fh:   # LF, not the platform newline: sha256sum -c and whoami.py read the lines verbatim
    fh.write("\n".join(lines) + "\n")
print(f"wrote {out} ({len(lines)} files); manifest sha256 {hashlib.sha256(open(out,'rb').read()).hexdigest()}")
