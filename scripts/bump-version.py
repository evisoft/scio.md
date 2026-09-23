#!/usr/bin/env python3
"""Set the plugin's version in every file that declares it: bump-version.py 0.8.5 (scripts/release.sh runs it).

Every marketplace reads the version from a different file; one left behind shows an old version for as long as nobody
notices. Python rather than `sed -i`, which takes a backup suffix on macOS and a script on Linux, so the same release
command works on both. Exits non-zero, writing nothing, when a file no longer spells its version the way this expects."""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# (file, pattern of the version it carries) — JSON manifests, then the skills' YAML front matter
FILES = (
    (".claude-plugin/plugin.json", r'"version": "[0-9.]*"'),
    (".claude-plugin/marketplace.json", r'"version": "[0-9.]*"'),
    (".cursor-plugin/plugin.json", r'"version": "[0-9.]*"'),
    (".cursor-plugin/marketplace.json", r'"version": "[0-9.]*"'),
    ("plugin.json", r'"version": "[0-9.]*"'),
    ("gemini-extension.json", r'"version": "[0-9.]*"'),
    ("skills/scio/SKILL.md", r'(?m)^  version: "[0-9.]*"'),
    ("openclaw/scio/SKILL.md", r'(?m)^  version: "[0-9.]*"'),
)


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit("usage: bump-version.py <version, e.g. 0.8.5>")
    version = sys.argv[1]
    updated = {}
    for rel, pattern in FILES:
        text = (ROOT / rel).read_bytes().decode("utf-8")   # bytes in, bytes out: line endings stay as they were
        spelled = '"version": "%s"' % version if pattern.startswith('"') else '  version: "%s"' % version
        new, n = re.subn(pattern, spelled, text)
        if not n:
            sys.exit(f"bump-version.py: {rel} carries no version this recognises; nothing written")
        updated[rel] = new
    for rel, text in updated.items():   # written only once every file was understood: a half-bumped tree is worse than none
        (ROOT / rel).write_bytes(text.encode("utf-8"))
    print(f"version {version} in {len(updated)} files")


if __name__ == "__main__":
    main()
