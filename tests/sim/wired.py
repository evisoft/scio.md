#!/usr/bin/env python3
"""After setup: does the harness launch the redirected copy's bridge? A deterministic check, no model needed.

A simulation proves nothing about a harness whose `scio` server is some other tree — the published plugin fetched
from GitHub, a copy left in the image, or nothing at all — because the harness's own turn then never reaches the
stand-in, and nothing said so. This reads the configuration the harness itself will read, finds the command its
`scio` server runs, and passes only when that is a scio_bridge.py whose scio_common.py is aimed at --base-url.

  wired.py --harness codex|gemini|kimi --home HOME --base-url URL      the file setup.py wrote under HOME
  wired.py --harness claude --plugin DIR --base-url URL                the plugin directory given to --plugin-dir
  wired.py --harness grok --home HOME --base-url URL                   the plugin `grok plugin install` copied
"""
import argparse, glob, json, os, re, sys


def bridge_of_mcp_json(path, root=None):
    """The bridge path an .mcp.json-style file launches for `scio`, with ${CLAUDE_PLUGIN_ROOT} expanded the way Claude
    Code and Grok expand it (to the plugin's own directory)."""
    with open(path, encoding="utf-8") as f:
        server = (json.load(f).get("mcpServers") or {}).get("scio") or {}
    args = server.get("args") or []
    if isinstance(server.get("command"), list):   # OpenCode's form: the command and its arguments in one list
        args = server["command"][1:]
    first = next((a for a in args if isinstance(a, str) and a.endswith("scio_bridge.py")), None)
    return first.replace("${CLAUDE_PLUGIN_ROOT}", root) if first and root else first


def bridge_of_codex(home):
    """Codex: [mcp_servers.scio] in ~/.codex/config.toml. setup.py writes its args as a JSON array (JSON strings are TOML
    strings), so no TOML parser is needed — tomllib is not there before Python 3.11."""
    path = os.path.join(home, ".codex", "config.toml")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        table = re.search(r"(?ms)^\[mcp_servers\.scio\]\s*$(.*?)(?=^\[)", f.read() + "\n[")
    args = re.search(r"(?m)^args\s*=\s*(\[.*\])", table.group(1)) if table else None
    try:
        return next((a for a in json.loads(args.group(1)) if a.endswith("scio_bridge.py")), None) if args else None
    except ValueError:
        return None


def configured_bridge(harness, home, plugin):
    """(the bridge the harness will launch, where that was read) — (None, what was looked at) when nothing is set."""
    if harness == "claude":
        path = os.path.join(plugin or "", ".mcp.json")
        return (bridge_of_mcp_json(path, os.path.abspath(plugin)) if plugin and os.path.exists(path) else None), path
    if harness == "grok":   # --home's .grok, then GROK_HOME when the run set one (grok and setup.py honour it)
        homes = [os.path.join(home, ".grok")] + ([os.environ["GROK_HOME"]] if os.environ.get("GROK_HOME") else [])
        for grok in homes:
            for path in sorted(glob.glob(os.path.join(grok, "installed-plugins", "*", ".mcp.json"))):
                found = bridge_of_mcp_json(path, os.path.dirname(path))
                if found and aimed_at(found):
                    return found, path
        return None, " or ".join(os.path.join(g, "installed-plugins") for g in homes)
    if harness == "codex":
        return bridge_of_codex(home), os.path.join(home, ".codex", "config.toml")
    path = {"gemini": os.path.join(home, ".gemini", "settings.json"),
            "kimi": os.path.join(os.environ.get("KIMI_CODE_HOME") or os.path.join(home, ".kimi-code"), "mcp.json")}.get(harness)
    if not path:
        sys.exit(f"wired.py: no reader for harness {harness!r}")
    return (bridge_of_mcp_json(path) if os.path.exists(path) else None), path


def aimed_at(bridge):
    """The wiki address the bridge's own tree is fixed to (scio_common.SCIO_HOST), or None."""
    common = os.path.join(os.path.dirname(os.path.dirname(bridge)), "scripts", "scio_common.py")
    try:
        with open(common, encoding="utf-8") as f:
            found = re.search(r'(?m)^SCIO_HOST = "([^"]+)"', f.read())
    except OSError:
        return None
    return found.group(1) if found else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--harness", required=True)
    ap.add_argument("--home", default=os.path.expanduser("~"))
    ap.add_argument("--plugin", help="claude: the plugin directory the session loads with --plugin-dir")
    ap.add_argument("--base-url", required=True)
    a = ap.parse_args()
    bridge, where = configured_bridge(a.harness, a.home, a.plugin)
    if not bridge:
        print(f"  FAIL {a.harness} launches no scio server (read {where})")
        return 1
    host = aimed_at(bridge)
    if host != a.base_url:
        print(f"  FAIL {a.harness} launches {bridge}, aimed at {host or 'nothing readable'}, not the stand-in at {a.base_url}")
        return 1
    print(f"  ok   {a.harness} launches the redirected copy ({bridge}, from {where})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
