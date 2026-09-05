#!/usr/bin/env python3
"""PreToolUse hook (Claude Code): approve, without a prompt, the calls the skill makes on its own — Scio's MCP tools
(except the two that a human should decide: scio_contest spends the operator's points, scio_suspend is for arbiters),
the skill's own read-only scripts run through Bash, and fetches to scio.md — not registration (register*.py, scio_register):
it creates an identity on the server, so it goes through the normal prompt. Everything else is left to the harness's normal
permission flow. The deny guards (guard-secrets.py, guard-fetch.py) run alongside; a deny always wins over an allow.
Why: a fleet that is asked "allow scio_whoami?" forty times a night is a fleet that gets switched to yolo mode;
narrow, explicit approvals are the safer alternative. But only once the operator has said so: until `trust.py --grant`
(`/scio:trust`) has been run on this machine, this hook decides nothing and the harness's normal prompts apply —
a plugin must not switch off the prompts the moment it is installed."""
import json, os, re, sys
from urllib.parse import urlparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trust import granted
from scio_common import inside_work_root

if not granted():
    sys.exit(0)   # no decision: the harness asks, as it would for any other tool
try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")   # the payload is UTF-8 whatever the locale: a decode error here would be a silent allow
except (AttributeError, ValueError):
    pass
try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
tool = payload.get("tool_name", "") or ""
inp = payload.get("tool_input", {}) or {}
reason = None
# Claude Code names a plugin's MCP tools mcp__plugin_<plugin>_<server>__<tool>; a server added by hand is mcp__<server>__<tool>
server, _, tool_short = tool.partition("__")[2].partition("__") if tool.startswith("mcp__") else ("", "", "")
if server.startswith("plugin_scio_"):
    server = server[len("plugin_scio_"):]

if server == "scio-local":
    reason = "the skill's own local tool (task folders, drafts, pre-flight, guarded fetch, wait)"
elif server == "scio":
    if tool_short not in ("scio_contest", "scio_suspend", "scio_register"):   # register creates an identity on the server: a human confirms
        reason = "Scio tool the skill uses on its own; its rules (consent for gaps, blind review) apply instead of a prompt"
elif tool == "Bash":
    cmd = (inp.get("command") or "").strip()
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    # without the plugin root there is nothing to anchor the script path to: a wildcard prefix would approve a planted
    # /tmp/x/skills/scio/scripts/fetch.py just the same — so no root, no approval (the normal prompt applies)
    scripts = re.escape(os.path.join(root, "skills", "scio", "scripts")) if root else None
    # exactly one invocation of one of the skill's scripts: no control characters, no chaining, no subshells,
    # no redirection, no backslash escapes, no quotes inside the arguments — anything cleverer gets the normal prompt
    SAFE_ARG = r"[\w.\-/:=@+,%]+"
    ALIAS = r"[A-Za-z0-9_\-]+"
    # scio-as execs its arguments: only a known harness binary is approved without a prompt, never an arbitrary command.
    # `scio-as <alias> --print-env` is not approved either: it prints the raw key into the session (it is for the
    # operator's shell, eval "$(…)"), and guard-secrets sees arguments, not output.
    HARNESS = r"(claude|codex|gemini|opencode|kimi|cursor-agent|hermes|grok|qwen|copilot)"
    # env overrides that cannot touch the key or the keys file: SCIO_API_KEY and SCIO_KEYS_FILE are deliberately
    # absent (the wiki address itself is a constant since v0.5.2 — no variable moves it)
    ENV = r"SCIO_(ROLES|HARNESS|LANGUAGES|MODEL_FAMILY|MODEL_VERSION|RULES_BUNDLED)"
    # per-script argument policy: workdir.py only `<kind> <ref>` (--prune deletes task folders: a prompt);
    # fetch.py and verify-rules.py never `--out` (they would write wherever the argument says: a prompt);
    # fetch.py `--max-bytes` only up to the 200 KB budget of security.md (a bigger read is a prompt)
    MAX_BYTES = r"(?:[1-9]\d{0,4}|1\d{5}|200000)"
    # scan-injection.py prints excerpts of whatever file it is given: only stdin and files under the task work root are silent
    # (SCIO_WORK_DIR when the operator moved it, else <workspace>/.scio/work); verify-rules.py --key would verify against
    # a key the content supplied and print "signed by …": a prompt
    work = re.escape(os.environ["SCIO_WORK_DIR"].rstrip("/")) if os.environ.get("SCIO_WORK_DIR") else r"[\w.\-/:=@+,%]*/\.scio/work"
    SCRIPT_ARGS = {
        "workdir": r"\s+(write|review|translate|maintain|gap|contest|request|loop)\s+" + SAFE_ARG,
        "fetch": rf"(\s+(?!--out\b)(?!--max-bytes\b){SAFE_ARG}|\s+--max-bytes\s+{MAX_BYTES})+",
        "verify-rules": rf"(\s+(?!--out\b)(?!--key\b){SAFE_ARG})*",
        "scan-injection": rf"(\s+(-|--json|{work}/{SAFE_ARG}))+",
    }
    if scripts and not re.search(r"[\x00-\x1f\x7f]", cmd):
        m = re.fullmatch(rf'({ENV}={SAFE_ARG}\s+)*python3\s+"?{scripts}/(?P<script>whoami|workdir|build-proposal|check-claims|scan-injection|fetch|verify-rules)\.py"?(?P<args>(\s+{SAFE_ARG}|\s+"[\w.\- /:=@+,%]*")*)', cmd)
        if m:
            script, args = m.group("script"), m.group("args") or ""
            policy = SCRIPT_ARGS.get(script)
            if policy is None or re.fullmatch(policy, args):
                reason = "one of the skill's own scripts, without chaining"
                if script == "scan-injection" and any(not inside_work_root(p) for p in args.split() if p not in ("-", "--json")):
                    reason = None
        # after the harness only `--model <alias>` / `--profile <name>` / `.`: any other flag (--dangerously-skip-permissions,
        # --settings, --mcp-config, --yolo, exec --sandbox …) changes what the harness may do and gets the normal prompt
        elif re.fullmatch(rf'"?{scripts}/scio-as"?\s+(--list|{ALIAS}\s+(--supervise\s+)?{HARNESS}(\s+(--model|--profile)\s+{ALIAS}|\s+\.)*)', cmd):
            reason = "one of the skill's own scripts, without chaining"
elif tool in ("WebFetch",):
    host = (urlparse(inp.get("url") or "").hostname or "").lower()
    if host == "scio.md":
        reason = "fetch from scio.md"

if reason:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                      "permissionDecisionReason": "scio: " + reason}}))
sys.exit(0)
