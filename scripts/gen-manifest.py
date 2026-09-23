#!/usr/bin/env python3
"""Write the two manifests an installed copy is verified against — the SHA-256 of every file they cover:

  skills/scio/MANIFEST.sha256   every file of the skill (the installable tree; a skill-only install has this alone)
  PLUGIN.sha256                 what a harness loads from the plugin root: hooks, MCP server definitions, slash commands,
                                sub-agents, the harness manifests and configuration snippets (PLUGIN_ENTRIES below)

  gen-manifest.py                     write both, for this repository (scripts/release.sh does, LAST)
  gen-manifest.py <skill dir>         the skill's manifest alone, for that tree (tests pass a copy)
  gen-manifest.py --plugin <root>     the plugin root's manifest alone, for that tree
  gen-manifest.py --check [...]       write nothing; exit 1 naming what differs — sha256sum -c, on every system
  gen-manifest.py --notes             the two manifests' own hashes, for the release notes

Lives in the repository's scripts/, not in the skill: it is a release tool, not something an installed agent runs.
whoami.py verifies the installed copy at session start and warns when a file differs (beyond CRLF line endings, which a
Windows checkout produces) or is present unlisted. The skill is the agents' shared brain and the hooks decide which
guards run: a modified SKILL.md, workflow, hook or command is the highest-value attack there is, and a checksum is the
cheapest thing that makes it visible. The manifests are committed with the release, and release.sh prints their own
hashes in the GitHub release notes so an installed copy can be checked end to end.

What is hashed is what git ships: in a git checkout the files git tracks or would add (never an ignored one — a
`.scio/` work folder left inside the skill would otherwise be listed, shipped by nobody, and reported missing by every
install); elsewhere the directory. On both sides, and in whoami.py, dotfiles and `__pycache__` below the covered roots
are left out. The skill ships text files only: the hashes are of the LF form (a CRLF checkout must yield this same
manifest), and a file with a lone CR or a NUL byte could not be hashed that way and verified with `sha256sum -c` alike,
so it is refused."""
import argparse, hashlib, os, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "skills", "scio")
SKILL_MANIFEST, PLUGIN_MANIFEST = "MANIFEST.sha256", "PLUGIN.sha256"
# What a harness reads from the plugin root (Claude Code, Cursor, Gemini, Grok…) or setup.py renders into a harness's
# own configuration. The skill is not here: it has its own manifest, and a skill-only install carries that one alone.
PLUGIN_ENTRIES = (".claude-plugin", ".cursor-plugin", ".mcp.json", "mcp.json", "mcp_config.json", "cursor.mcp.json",
                  "copilot.mcp.json", "plugin.json", "gemini-extension.json", "GEMINI.md", "hooks.json", "hooks",
                  "commands", "agents", "codex", "gemini", "opencode", "vscode", "antigravity", "openclaw")


def skipped(parts):
    """Below a covered root: dotfiles, dot-folders and bytecode are what a machine leaves behind, never what ships."""
    return any(p.startswith(".") or p == "__pycache__" for p in parts) or parts[-1].endswith(".pyc")


def git_files(root):
    """Paths under `root` that git tracks or would add, relative to it — None outside a git work tree."""
    try:
        inside = subprocess.run(["git", "-C", root, "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=30)
        if inside.returncode or inside.stdout.strip() != "true":
            return None
        listed = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
                                capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode:
        return None
    names = [n.decode("utf-8") for n in listed.stdout.split(b"\0") if n]
    return [n for n in names if os.path.isfile(os.path.join(root, n))] or None   # deleted but still tracked: not shipped


def walked_files(root, entries=None):
    found = []
    for top in (entries if entries is not None else [""]):
        start = os.path.join(root, top) if top else root
        if os.path.isfile(start):
            found.append(top)
            continue
        for dirpath, dirs, files in os.walk(start):
            dirs[:] = sorted(dirs)
            found += [os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/") for f in files]
    return found


def covered(root, plugin):
    """The sorted relative paths one manifest lists."""
    names = git_files(root)
    names = walked_files(root, PLUGIN_ENTRIES if plugin else None) if names is None else names
    keep = set()
    for rel in names:
        parts = rel.replace(os.sep, "/").split("/")
        if plugin:
            if parts[0] not in PLUGIN_ENTRIES or (len(parts) > 1 and skipped(parts[1:])):
                continue
        elif rel in (SKILL_MANIFEST, PLUGIN_MANIFEST) or skipped(parts):
            continue
        keep.add("/".join(parts))
    return sorted(keep)


def lines_for(root, plugin):
    """(manifest lines, files refused by the LF rule)."""
    lines, refused = [], []
    for rel in covered(root, plugin):
        with open(os.path.join(root, rel), "rb") as fh:
            data = fh.read().replace(b"\r\n", b"\n")   # hash the LF form: the one rule shared with whoami.py, so a CRLF checkout (git core.autocrlf, the Windows default) yields the release's manifest
        if b"\r" in data or b"\0" in data:
            refused.append(rel)
            continue
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
    return lines, refused


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def produce(root, plugin, check):
    """Write (or, with check, compare) one manifest; return a problem string, or "" when all is well."""
    name = PLUGIN_MANIFEST if plugin else SKILL_MANIFEST
    out = os.path.join(root, name)
    lines, refused = lines_for(root, plugin)
    if refused:
        return (f"ERROR: not text with LF (or CRLF) line endings, so the LF-form hash and sha256sum -c would disagree: "
                f"{', '.join(refused)}; nothing written")
    text = "\n".join(lines) + "\n"
    if check:
        try:
            with open(out, "rb") as fh:
                have = fh.read().decode("utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            return f"{out} is missing or unreadable"
        if have == text:
            print(f"{out}: {len(lines)} files verified")
            return ""
        was, now = set(have.splitlines()), set(lines)
        differ = sorted({l.split("  ", 1)[-1] for l in was ^ now})
        return f"{out} does not match the tree ({len(differ)}: {', '.join(differ[:8])}); run scripts/gen-manifest.py"
    with open(out, "w", encoding="utf-8", newline="\n") as fh:   # LF, not the platform newline: sha256sum -c and whoami.py read the lines verbatim
        fh.write(text)
    print(f"wrote {out} ({len(lines)} files); manifest sha256 {digest(out)}")
    return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("skill", nargs="?", help="a skill directory: its manifest alone")
    ap.add_argument("--plugin", metavar="ROOT", help="a plugin root: its manifest alone")
    ap.add_argument("--check", action="store_true", help="compare, write nothing; exit 1 on a difference")
    ap.add_argument("--notes", action="store_true", help="print the two manifests' own hashes (release notes)")
    a = ap.parse_args()
    if a.notes:
        print(" · ".join(f"{name} sha256: {digest(path)}" for name, path in
                         ((SKILL_MANIFEST, os.path.join(SKILL, SKILL_MANIFEST)), (PLUGIN_MANIFEST, os.path.join(REPO, PLUGIN_MANIFEST)))))
        return
    jobs = []
    if a.skill:
        jobs.append((os.path.abspath(a.skill), False))
    if a.plugin:
        jobs.append((os.path.abspath(a.plugin), True))
    jobs = jobs or [(SKILL, False), (REPO, True)]
    for root, plugin in jobs:
        if not os.path.isfile(os.path.join(root, ".claude-plugin", "plugin.json") if plugin else os.path.join(root, "SKILL.md")):
            what = ".claude-plugin/plugin.json, so it is not a plugin root" if plugin else "SKILL.md, so it is not a skill"
            print(f"usage: gen-manifest.py [<skill dir>] [--plugin <root>] [--check]   -- {root} has no {what}; nothing written",
                  file=sys.stderr)
            sys.exit(2)
    problems = [p for p in (produce(root, plugin, a.check) for root, plugin in jobs) if p]
    if problems:
        sys.exit("\n".join(problems))


if __name__ == "__main__":
    main()
