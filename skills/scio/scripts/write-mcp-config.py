#!/usr/bin/env python3
"""Compatibility shim: `write-mcp-config.py [<alias>|-] antigravity [--workspace] [--yes]` now runs
`setup.py --harness antigravity [--alias <alias>] [--workspace] [--yes]`, the single writer of Antigravity's mcp_config.json
(both servers are local since v0.4 and read the keys file; no key goes into the file)."""
import os, subprocess, sys

a = sys.argv[1:]
if len(a) < 2 or a[1] != "antigravity":
    print(__doc__.strip()); sys.exit(2)
cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup.py"), "--harness", "antigravity"]
if a[0] != "-":
    cmd += ["--alias", a[0]]
if "--workspace" in a:
    cmd.append("--workspace")
if "--yes" in a:   # setup.py asks before writing: a caller that cannot answer passes --yes, as to setup.py itself
    cmd.append("--yes")
sys.exit(subprocess.call(cmd))
