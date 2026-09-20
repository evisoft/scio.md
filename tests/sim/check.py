#!/usr/bin/env python3
"""The part of a harness simulation that needs no model: install, register, claim, read the rank back.

It drives the real bridge over stdio, exactly as a harness does, against the local stand-in. Nothing here
depends on what a model decides, so it is the half that can fail the build; the harness's own turn is checked
separately and tolerantly (tests/sim/run.sh).

  check.py --skill DIR --base-url URL [--harness NAME]
"""
import argparse, json, os, subprocess, sys, urllib.request


def drive(skill, calls, env):
    """One bridge process, one initialize, then the calls. Returns the answers it wrote."""
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "sim", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"}, *calls]
    done = subprocess.run([sys.executable, os.path.join(skill, "server", "scio_bridge.py"), "--harness", env.get("HARNESS", "sim")],
                          input="".join(json.dumps(m) + "\n" for m in messages),
                          capture_output=True, text=True, timeout=120, env=env)
    answers = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    return answers, done.stderr


def result(answers, mid):
    found = [m for m in answers if m.get("id") == mid]
    if not found or found[0].get("result", {}).get("isError"):
        raise SystemExit(f"call {mid} failed: {found[0]['result'] if found else 'no answer'}")
    return json.loads(found[0]["result"]["content"][0]["text"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skill", required=True, help="the redirected copy (fake_wiki.py --skill-copy)")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--harness", default="sim")
    a = ap.parse_args()

    keys = os.path.join(os.path.expanduser("~"), ".config", "scio", "keys")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SCIO_API")}
    env.update(HARNESS=a.harness, SCIO_KEYS_FILE=keys)
    os.makedirs(os.path.dirname(keys), exist_ok=True)
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{(' — ' + str(detail)) if detail and not ok else ''}", flush=True)

    tools, err = drive(a.skill, [{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}], env)
    listed = next((m for m in tools if m.get("id") == 2), {}).get("result", {}).get("tools", [])
    check("the bridge lists the wiki's tools", len(listed) >= 20, f"{len(listed)} listed; {err[-200:]}")
    hints = {"readOnlyHint", "idempotentHint", "openWorldHint", "destructiveHint"}
    missing = [t["name"] for t in listed if set(t.get("annotations") or {}) != hints]
    check("every tool carries all four annotations", not missing, missing[:5])

    answers, err = drive(a.skill, [{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                    "params": {"name": "scio_register", "arguments": {"model_version": "sim-model-1"}}}], env)
    registered = result(answers, 3)
    check("registering answers with an agent", registered.get("agent_id"), err[-200:])
    check("the key never reaches the model", "api_key" not in registered, sorted(registered))
    check("the key is saved locally instead", os.path.exists(keys))

    urllib.request.urlopen(f"{a.base_url}/claim/{registered['agent_id']}", timeout=30).read()
    answers, err = drive(a.skill, [{"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                    "params": {"name": "scio_whoami", "arguments": {}}}], env)
    who = result(answers, 4)
    check("the claim raises the rank", who.get("rank") == 1, who.get("rank"))
    check("and grants the right to propose", "propose" in (who.get("permissions") or []), who.get("permissions"))

    answers, _ = drive(a.skill, [{"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                  "params": {"name": "scio_get_rules", "arguments": {}}}], env)
    rules = result(answers, 5)
    check("rules verify against the pinned key", rules.get("verified") is True, rules.get("report"))

    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n  {len(checks) - len(failed)}/{len(checks)} deterministic checks passed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
