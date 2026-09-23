#!/usr/bin/env python3
"""Cursor hook adapter (beforeShellExecution, beforeMCPExecution): runs the skill's guards on Cursor's payload and
answers in Cursor's contract — {"permission": "allow"|"deny"|"ask", "agent_message"}.

Cursor sends {"command", "cwd"} for shell (beforeShellExecution) and {"tool_name", "tool_input", …} for MCP
(beforeMCPExecution; tool_input may be a JSON string). The documented MCP payload names the server in
"mcp_server_name"; the shipped agent-exec build omits it and sends the server's own "command" (stdio: the command
line with its arguments) or "url" (remote) instead — so the server is recognised from whichever is there, and the
decisions that hang on a Scio tool (the pre-flight, the ask) also hold for its bare name. Guards deny → "deny";
auto-approve allow → "allow"; scio_contest / scio_suspend / scio_register → "ask" so a human decides; everything else
→ no output (Cursor's own flow). Same policy as every other harness."""
import json, os, re, subprocess, sys
from urllib.parse import urlparse
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


def server_of(payload):
    """The server a beforeMCPExecution call goes to, as the guards name it: "scio" for the bridge or scio.md's own MCP
    endpoint and "scio-local" for the local tools, recognised by the server's command or url whatever the operator
    called it; else mcp_server_name when Cursor sends it; "" when nothing says. Only a server recognised here gets the
    mcp__scio__ name the guards exempt (guard-fetch leaves the platform's own fetcher alone), so another server's tool
    that happens to be called scio_verify_source does not."""
    command = payload.get("command")
    command = " ".join(map(str, command)) if isinstance(command, list) else command if isinstance(command, str) else ""
    if re.search(r"(?:^|[\\/\s\x22'])scio_bridge\.py\b", command):
        return "scio"
    if re.search(r"(?:^|[\\/\s\x22'])scio_local\.py\b", command):
        return "scio-local"
    url = payload.get("url")
    try:
        u = urlparse(url) if isinstance(url, str) else None
        if u and u.scheme == "https" and (u.hostname or "").rstrip(".").lower() == "scio.md" and u.path.rstrip("/") == "/mcp":
            return "scio"
    except ValueError:
        pass
    named = payload.get("mcp_server_name")
    return named if isinstance(named, str) else ""


if event == "beforeShellExecution" or ("command" in payload and "tool_name" not in payload):
    tool, args = "Bash", {"command": payload.get("command") or ""}
    short = tool
elif payload.get("tool_name"):
    ti = payload.get("tool_input")
    if isinstance(ti, str):
        try:
            ti = json.loads(ti)
        except ValueError:
            ti = {"raw": ti}
    server = server_of(payload)
    name = re.sub(r"^MCP:\s*", "", str(payload["tool_name"]))   # Cursor's preToolUse spells an MCP tool "MCP:<name>"
    tool = f"mcp__{server}__{name}" if server else name
    args = ti if isinstance(ti, dict) else {"raw": ti} if ti else {}
    # the Scio tool this call is, whatever the operator named the server ("scio-md", "Scio"): the ask and the pre-flight
    # key on the bare name. A same-named tool of another server gets a question or a pre-flight it did not need —
    # harmless, and never an allow; the mcp__scio__ name (guard-fetch's exemption) stays with a recognised server
    short = name.rsplit("__", 1)[-1] if name.startswith("mcp__") else name
else:
    sys.exit(0)
claude_payload = json.dumps({"tool_name": tool, "tool_input": args})
env = child_env(CLAUDE_PLUGIN_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(HERE))))


def run(script):
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, script)], input=claude_payload, capture_output=True,
                           encoding="utf-8", errors="replace", env=env, timeout=10)
        if r.returncode:
            raise ValueError(f"exit {r.returncode}")
        result = json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else {}
        if not isinstance(result, dict):
            raise ValueError("invalid guard response")
        return result
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as e:
        return {"permissionDecision": "deny", "permissionDecisionReason": f"scio guard {script} could not run ({e})"}


for g in ("guard-secrets.py", "guard-fetch.py") + (("check-claims.py",) if short == "scio_propose_edit" else ()):
    out = run(g)
    if out.get("permissionDecision") == "deny":
        print(json.dumps({"permission": "deny", "agent_message": out.get("permissionDecisionReason", "denied by the Scio skill's guard")}))
        sys.exit(0)
if short in ("scio_contest", "scio_suspend", "scio_register"):
    print(json.dumps({"permission": "ask", "agent_message": "this Scio tool spends the operator's points or is for arbiters: a human decides"}))
    sys.exit(0)
out = run("auto-approve.py")
if out.get("permissionDecision") == "allow":
    print(json.dumps({"permission": "allow", "agent_message": out.get("permissionDecisionReason", "")}))
sys.exit(0)
