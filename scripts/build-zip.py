#!/usr/bin/env python3
"""Zip the plugin for claude.ai and Cowork (Customize → Plugins → Add → Upload plugin), and the skill alone for the
Claude API and Managed Agents (POST /v1/skills) and claude.ai's own skill upload.

  build-zip.py                  write dist/scio-<version>.zip, dist/scio-skill-<version>.zip and
                                dist/scio-openai-<version>.zip (the version of .claude-plugin/plugin.json), one line
                                each, in that order: path, file count, SHA-256
  build-zip.py --out <dir>      write them there instead (tests pass a temporary folder)

The archive holds one top-level folder, `scio/`, with `.claude-plugin/plugin.json` one level down — the layout the upload
accepts. What goes in is what the two manifests list and nothing else: PLUGIN.sha256 (what a harness loads from the
plugin root) and skills/scio/MANIFEST.sha256 (the skill), the manifests themselves, LICENSE and README.md. So the copy a
Cowork session unpacks passes whoami.py's check at session start — no listed file missing, none unlisted — and a test,
a fixture or a release tool can never ride along. Text is stored in the LF form the manifests hash; entries are sorted
and dated 2020-01-01, so the same tree always gives the same bytes and the SHA-256 in the release notes is reproducible.

What each surface loads from it (claude.com/docs/plugins/platform-support): chat loads the skill and the commands (as
skills) — agents, hooks and the local MCP servers are skipped there; Cowork loads all of it when the session runs on
the operator's computer, with python3 for the two stdio servers and the hooks.

The skill archive is skills/scio alone under one `scio/` folder — what MANIFEST.sha256 lists, and the manifest — the layout
POST /v1/skills accepts (SKILL.md at the top of a single enclosing folder, under 30 MB) and the skill lands in as
/skills/scio/.

The OpenAI archive is what the OpenAI plugin portal accepts (developers.openai.com/plugins/deploy/submission): the
portable root plugin.json, mcp.json (Scio's OAuth server) and the skill, under one `scio/` folder. ZIPs with lifecycle
hooks cannot be submitted, so it carries no hooks/ and its plugin.json drops `extensions.com.openai.hooks`; the
repository's plugin.json keeps the guards for manual Codex installs, which may run hooks. A release tool, not part of
the skill."""
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


KINDS = {"plugin": "scio-{v}.zip", "skill": "scio-skill-{v}.zip", "openai": "scio-openai-{v}.zip"}


def members(root, kind="plugin"):
    """Every path the archive holds, relative to `root` (the plugin root, or the skill for the skill archive), from the
    manifests."""
    if kind == "skill":
        paths = {"MANIFEST.sha256"} | set(listed(os.path.join(root, "MANIFEST.sha256")))
        return checked(root, paths)
    skill = "skills/scio"
    if kind == "openai":
        paths = set(EXTRA) | {"plugin.json", "mcp.json", f"{skill}/MANIFEST.sha256"}
        paths |= {f"{skill}/{rel}" for rel in listed(os.path.join(root, skill, "MANIFEST.sha256"))}
        return checked(root, paths)
    paths = set(EXTRA) | {"PLUGIN.sha256", f"{skill}/MANIFEST.sha256"}
    paths |= set(listed(os.path.join(root, "PLUGIN.sha256")))
    paths |= {f"{skill}/{rel}" for rel in listed(os.path.join(root, skill, "MANIFEST.sha256"))}
    return checked(root, paths)


def checked(root, paths):
    for rel in sorted(paths):
        parts = rel.split("/")
        if REFUSED & set(parts) or parts[0] == "bin" or ".." in parts or rel.startswith("/"):
            raise SystemExit(f"build-zip.py: refusing to package {rel}")
        full = os.path.join(root, rel)
        if os.path.islink(full) or not os.path.isfile(full):
            raise SystemExit(f"build-zip.py: {rel} is listed but is not a regular file here — run scripts/gen-manifest.py")
    return sorted(paths)


def without_hooks(data):
    """The portable plugin.json minus `extensions.com.openai.hooks`, for the portal that refuses hooks."""
    manifest = json.loads(data)
    manifest.get("extensions", {}).get("com.openai", {}).pop("hooks", None)
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# The portal reads a server's authentication only from `extensions["com.openai"].auth` in mcp.json and shows
# "Authentication: Unavailable" without it. The Agent Plugins 1.0.0 schema refuses that key on a server, and Codex
# finds the OAuth flow by discovery, so the repository's mcp.json stays schema-valid and only the portal's copy has it:
# OAuth with a client ID metadata document (ChatGPT's https://chatgpt.com/oauth/client.json, which scio.md accepts:
# `client_id_metadata_document_supported`) and the one scope it offers. scio.md also offers DCR, OpenAI's fallback.
PORTAL_AUTH = {"type": "oauth", "client": {"mode": "cimd"}, "baseScopes": ["scio"]}


def with_portal_auth(data):
    config = json.loads(data)
    for server in config["mcpServers"].values():
        server.setdefault("extensions", {}).setdefault("com.openai", {})["auth"] = PORTAL_AUTH
    return (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build(root, out_dir, kind="plugin"):
    with open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, KINDS[kind].format(v=version))
    if kind == "skill":
        root = os.path.join(root, "skills", "scio")
    paths = members(root, kind)
    tmp = target + ".part"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in paths:
            full = os.path.join(root, rel)
            with open(full, "rb") as f:
                data = f.read().replace(b"\r\n", b"\n")   # the form the manifests hash, whatever the checkout did
            if kind == "openai" and rel == "plugin.json":
                data = without_hooks(data)
            if kind == "openai" and rel == "mcp.json":
                data = with_portal_auth(data)
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
    for kind in KINDS:
        target, count, digest = build(os.path.abspath(args.root), os.path.abspath(args.out), kind)
        print(f"{target}  {count} files  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
