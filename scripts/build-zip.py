#!/usr/bin/env python3
"""Zip the plugin for claude.ai and Cowork: Customize → Plugins → Add → Upload plugin.

  build-zip.py                  write dist/scio-<version>.zip (the version of .claude-plugin/plugin.json)
  build-zip.py --out <dir>      write it there instead (tests pass a temporary folder)

The archive holds one top-level folder, `scio/`, with `.claude-plugin/plugin.json` one level down — the layout the upload
accepts. What goes in is what the two manifests list and nothing else: PLUGIN.sha256 (what a harness loads from the
plugin root) and skills/scio/MANIFEST.sha256 (the skill), the manifests themselves, LICENSE and README.md. So the copy a
Cowork session unpacks passes whoami.py's check at session start — no listed file missing, none unlisted — and a test,
a fixture or a release tool can never ride along. Text is stored in the LF form the manifests hash; entries are sorted
and dated 2020-01-01, so the same tree always gives the same bytes and the SHA-256 in the release notes is reproducible.

What each surface loads from it (claude.com/docs/plugins/platform-support): chat loads the skill and the commands (as
skills) — agents, hooks and the local MCP servers are skipped there; Cowork loads all of it when the session runs on
the operator's computer, with python3 for the two stdio servers and the hooks. A release tool, not part of the skill."""
import argparse, hashlib, json, os, stat, sys, zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = "scio"
EXTRA = ("LICENSE", "README.md")
# The upload refuses these (claude.com/docs/plugins/pre-submission-checklist), and a top-level bin/ makes chat and
# Cowork refuse the whole plugin.
REFUSED = {".DS_Store", "Thumbs.db", "desktop.ini", "__MACOSX", "__pycache__"}
STAMP = (2020, 1, 1, 0, 0, 0)


def listed(manifest):
    with open(manifest, encoding="utf-8") as f:
        return [line.split("  ", 1)[1] for line in f.read().splitlines() if "  " in line]


def members(root):
    """Every path the archive holds, relative to the plugin root, from the two manifests."""
    skill = "skills/scio"
    paths = set(EXTRA) | {"PLUGIN.sha256", f"{skill}/MANIFEST.sha256"}
    paths |= set(listed(os.path.join(root, "PLUGIN.sha256")))
    paths |= {f"{skill}/{rel}" for rel in listed(os.path.join(root, skill, "MANIFEST.sha256"))}
    for rel in sorted(paths):
        parts = rel.split("/")
        if REFUSED & set(parts) or parts[0] == "bin" or ".." in parts or rel.startswith("/"):
            raise SystemExit(f"build-zip.py: refusing to package {rel}")
        full = os.path.join(root, rel)
        if os.path.islink(full) or not os.path.isfile(full):
            raise SystemExit(f"build-zip.py: {rel} is listed but is not a regular file here — run scripts/gen-manifest.py")
    return sorted(paths)


def build(root, out_dir):
    with open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"scio-{version}.zip")
    paths = members(root)
    tmp = target + ".part"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in paths:
            full = os.path.join(root, rel)
            with open(full, "rb") as f:
                data = f.read().replace(b"\r\n", b"\n")   # the form the manifests hash, whatever the checkout did
            info = zipfile.ZipInfo(f"{TOP}/{rel}", date_time=STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3   # Unix, so the mode below is read
            mode = 0o755 if os.stat(full).st_mode & stat.S_IXUSR else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, data)
    os.replace(tmp, target)
    with open(target, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return target, len(paths), digest


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(REPO, "dist"), help="folder for the archive (default: dist/)")
    ap.add_argument("--root", default=REPO, help=argparse.SUPPRESS)
    args = ap.parse_args()
    target, count, digest = build(os.path.abspath(args.root), os.path.abspath(args.out))
    print(f"{target}  {count} files  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
