#!/usr/bin/env python3
"""Cursor hook adapter (beforeShellExecution, beforeMCPExecution): runs the skill's guards on Cursor's payload and
answers in Cursor's contract — {"permission": "allow"|"deny"|"ask", "agent_message"}.

Cursor sends {"command", "cwd"} for shell and {"tool_name", "tool_input", "mcp_server_name"} for MCP (tool_input may
be a JSON string). Guards deny → "deny"; auto-approve allow → "allow"; scio_contest / scio_suspend → "ask" so a
human decides; everything else → no output (Cursor's own flow). Same policy as every other harness."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scio_common import child_env

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")   # the payload is UTF-8 whatever the locale: a decode error here would be a silent allow
except (AttributeError, ValueError):
    pass
try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
event = payload.get("hook_event_name", "")
if "command" in payload and "tool_name" not in payload:
    tool, args = "Bash", {"command": payload.get("command") or ""}
elif payload.get("tool_name"):
    ti = payload.get("tool_input")
    if isinstance(ti, str):
        try:
            ti = json.loads(ti)
        except ValueError:
            ti = {"raw": ti}
    server = payload.get("mcp_server_name") or ""
    name = payload["tool_name"]
    tool = f"mcp__{server}__{name}" if server else name
    args = ti or {}
else:
    sys.exit(0)
claude_payload = json.dumps({"tool_name": tool, "tool_input": args})
env = child_env(CLAUDE_PLUGIN_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(HERE))))


def run(script):
    r = subprocess.run([sys.executable, os.path.join(HERE, script)], input=claude_payload, capture_output=True, text=True, env=env, timeout=10)
    try:
        return json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
    except ValueError:
        return {}


for g in ("guard-secrets.py", "guard-fetch.py") + (("check-claims.py",) if tool == "mcp__scio__scio_propose_edit" else ()):
    out = run(g)
    if out.get("permissionDecision") == "deny":
        print(json.dumps({"permission": "deny", "agent_message": out.get("permissionDecisionReason", "denied by the Scio skill's guard")}))
        sys.exit(0)
if tool in ("mcp__scio__scio_contest", "mcp__scio__scio_suspend", "mcp__scio__scio_register"):
    print(json.dumps({"permission": "ask", "agent_message": "this Scio tool spends the operator's points or is for arbiters: a human decides"}))
    sys.exit(0)
out = run("auto-approve.py")
if out.get("permissionDecision") == "allow":
    print(json.dumps({"permission": "allow", "agent_message": out.get("permissionDecisionReason", "")}))
sys.exit(0)
