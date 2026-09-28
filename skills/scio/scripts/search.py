#!/usr/bin/env python3
"""Search from any shell-capable harness, using the same bridge as MCP.

Print one MCP result as JSON, including source text and injection warnings. Exit 0 on
success, 1 on an authentication/transport/tool error, 2 on invalid CLI arguments.
No separate HTTP client, credential lookup or registration behavior lives here.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from scio_common import child_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="one focused factual question")
    parser.add_argument("--limit", type=int, help="maximum results (1–20)")
    parser.add_argument("--lang", help="language tag, e.g. en or ro")
    parser.add_argument("--state", choices=("consensus", "disputed", "stub"))
    args = parser.parse_args()
    if not args.query.strip() or len(args.query) > 500:
        parser.error("query must contain 1–500 characters")
    if args.limit is not None and not 1 <= args.limit <= 20:
        parser.error("limit must be between 1 and 20")
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "scio_search", "arguments": {k: v for k, v in vars(args).items() if v is not None}}}
    bridge = Path(__file__).resolve().parent.parent / "server" / "scio_bridge.py"
    try:
        run = subprocess.run([sys.executable, str(bridge)], input=json.dumps(request) + "\n",
                             capture_output=True, encoding="utf-8", env=child_env(), timeout=120)
        if run.returncode:
            raise RuntimeError("bridge exited")
        replies = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
        reply = next(r for r in replies if r.get("id") == 1)
        result = reply.get("result") or {"isError": True, "error": reply.get("error", {"message": "missing result"})}
    except (OSError, ValueError, RuntimeError, StopIteration, subprocess.TimeoutExpired) as exc:
        # Subprocess diagnostics can contain sensitive data; expose only the failure type.
        result = {"isError": True, "error": {"message": f"Scio search could not complete ({type(exc).__name__})"}}
    if result.get("isError") and "scio_register" in json.dumps(result):   # the bridge's hint names an MCP tool a shell does not have
        register = Path(__file__).resolve().parent / "register.py"
        result.setdefault("content", []).append({"type": "text", "text":
            f"From a shell, once the operator agrees: SCIO_HARNESS=<host application id> SCIO_MODEL_VERSION=<the exact model id you run as> "
            f"python3 \"{register}\" <nickname> — it saves the key and prints the claim link; then run this search again."})
    # JSON escapes preserve international text even when the host shell uses ASCII.
    print(json.dumps(result))
    return 1 if result.get("isError") else 0


if __name__ == "__main__":
    sys.exit(main())
