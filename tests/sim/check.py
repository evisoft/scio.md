#!/usr/bin/env python3
"""The part of a harness simulation that needs no model: install, register, claim, read the rank back.

It drives the real bridge over stdio, exactly as a harness does, against the local stand-in. Nothing here
depends on what a model decides, so it is the half that can fail the build; the harness's own turn is checked
separately and tolerantly (tests/sim/run.sh).

Every check must be able to fail on the wiki's side. So registration comes first and the tool list is read with
the key it saved: a keyless bridge adds the whole bundled contract to whatever the wiki sends (so that a harness
sees every tool before registering), and a listing check made keyless passed with no wiki running at all. When a
step the others stand on fails, the run stops there rather than report checks that tested nothing.

  check.py --skill DIR --base-url URL [--harness NAME]
"""
import argparse, json, os, subprocess, sys, urllib.request

HINTS = {"readOnlyHint", "idempotentHint", "openWorldHint", "destructiveHint"}


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
    """The structured answer to call `mid`, or None when it failed (the caller's check says so)."""
    found = [m for m in answers if m.get("id") == mid]
    res = (found[0].get("result") or {}) if found else {}
    if not res or res.get("isError"):
        return None
    if isinstance(res.get("structuredContent"), dict):
        return res["structuredContent"]
    try:
        return json.loads(res["content"][0]["text"])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def bundled_names(skill):
    """The tools the skill was released against (server/tools.json): a wiki that lists fewer lost some, or never had them."""
    with open(os.path.join(skill, "server", "tools.json"), encoding="utf-8") as f:
        return {t["name"] for t in json.load(f)["tools"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skill", required=True, help="the redirected copy (fake_wiki.py --skill-copy)")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--harness", default="sim")
    a = ap.parse_args()

    keys = os.path.join(os.path.expanduser("~"), ".config", "scio", "keys")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SCIO_API") and k != "SCIO_AGENT"}
    env.update(HARNESS=a.harness, SCIO_KEYS_FILE=keys)
    os.makedirs(os.path.dirname(keys), exist_ok=True)
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{(' — ' + str(detail)) if detail and not ok else ''}", flush=True)
        return bool(ok)

    def done():
        failed = [name for name, ok, _ in checks if not ok]
        print(f"\n  {len(checks) - len(failed)}/{len(checks)} deterministic checks passed", flush=True)
        return 1 if failed else 0

    # registered the way the skill tells an agent to (SKILL.md): a name, the family, the exact model id
    answers, err = drive(a.skill, [{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "scio_register", "arguments": {
        "display_name": f"sim-{a.harness}", "model_family": "other", "model_version": "sim-model-1"}}}], env)
    registered = result(answers, 3) or {}
    if not check("registering answers with an agent", registered.get("agent_id") and registered.get("claim_url"),
                 f"{[m.get('result') or m.get('error') for m in answers if m.get('id') == 3]} {err[-200:]}"):
        return done()   # nothing below means anything without an agent
    saved = []
    if os.path.exists(keys):
        with open(keys, encoding="utf-8") as f:
            saved = [line.split("=", 1)[1].strip() for line in f if "=" in line and not line.startswith("#")]
    check("the key never reaches the model", "api_key" not in registered and saved and not any(k in json.dumps(registered) for k in saved),
          sorted(registered))
    check("the key is saved locally instead", saved)

    tools, err = drive(a.skill, [{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}], env)
    listed = next((m for m in tools if m.get("id") == 2), {}).get("result", {}).get("tools", [])
    missing = sorted(bundled_names(a.skill) - {t.get("name") for t in listed})
    check("the bridge lists the wiki's tools", listed and not missing, f"{len(listed)} listed, missing {missing[:5]}; {err[-200:]}")
    no_hints = [t.get("name") for t in listed if set(t.get("annotations") or {}) != HINTS]
    check("every tool carries all four annotations", listed and not no_hints, no_hints[:5])

    try:   # the link the bridge handed over, opened as the operator would — never one rebuilt from the agent id
        urllib.request.urlopen(registered["claim_url"], timeout=30).read()
    except Exception as e:
        print(f"  (opening claim_url failed: {e})", flush=True)
    answers, err = drive(a.skill, [{"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                    "params": {"name": "scio_whoami", "arguments": {}}}], env)
    who = result(answers, 4) or {}
    check("the claim raises the rank", who.get("rank") == 1, who.get("rank"))
    check("and grants the right to propose", "propose" in (who.get("permissions") or []), who.get("permissions"))

    answers, _ = drive(a.skill, [{"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                  "params": {"name": "scio_get_rules", "arguments": {}}}], env)
    rules = result(answers, 5) or {}
    check("rules verify against the pinned key", rules.get("verified") is True, rules.get("report"))
    return done()


if __name__ == "__main__":
    sys.exit(main())
