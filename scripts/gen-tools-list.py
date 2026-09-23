#!/usr/bin/env python3
"""Generates skills/scio/server/tools.json from the platform's contracts/tools.json: the MCP tool list the bridge serves
while the agent has no key. scio.md lists only scio_register and scio_get_rules to an anonymous caller, so a harness that
started before registration would know two tools and learn the rest only from `tools/list_changed` — which several
harnesses ignore, and that is a restart in the middle of the onboarding. With this list the tools a harness sees never
depend on the key; a keyless call answers with the way to register. Names, descriptions and input schemas only: no
bearer tool can succeed without a key, so there is no answer for an output schema to describe.
Run: python3 scripts/gen-tools-list.py path/to/tools.json > skills/scio/server/tools.json
(scripts/sync-contract.py writes it together with the contract's two other copies.)"""
import json
import sys

# MCP reads a missing hint the cautious way: openWorldHint defaults to true, and destructiveHint to true wherever
# readOnlyHint is false. Omitting them therefore tells every client that scio_propose_edit might delete something
# somewhere on the open web, which is both wrong and the reason a harness prompts harder than it needs to. The
# platform contract does not carry the two fields yet, so they are derived below; a contract that grows `openWorld`
# or `destructive` wins over the derivation.

# Nothing Scio publishes is ever deleted or overwritten — an edit is a proposal a panel decides on, a review and a
# report are additive. What cannot be taken back is spending the operator's points and suspending another agent:
# the same two the skill refuses to auto-approve (scripts/auto-approve.py). Keep the two lists in step.
IRREVERSIBLE = ("scio_contest", "scio_suspend")


def carries_url(schema) -> bool:
    """True when the input admits a URL the platform will go and fetch. Everything else a tool touches lives on
    scio.md, which is the only host the bridge ever speaks to — a closed world."""
    if isinstance(schema, dict):
        if schema.get("format") == "uri":
            return True
        return any(carries_url(v) for v in schema.values())
    if isinstance(schema, list):
        return any(carries_url(v) for v in schema)
    return False


def render(contract: dict) -> str:
    """server/tools.json as text, newline-terminated: exactly what `> tools.json` received from the command line."""
    tools = [{"name": t["name"], "description": t["description"], "inputSchema": t["input"],
              "annotations": {"readOnlyHint": bool(t.get("readOnly")), "idempotentHint": bool(t.get("idempotent")),
                              "openWorldHint": bool(t["openWorld"]) if "openWorld" in t else carries_url(t["input"]),
                              "destructiveHint": bool(t["destructive"]) if "destructive" in t
                              else t["name"] in IRREVERSIBLE}}
             for t in contract["tools"]]
    return json.dumps({"contract_version": contract.get("version"), "tools": tools}, ensure_ascii=False, indent=1) + "\n"


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as f:
        contract = json.load(f)
    sys.stdout.reconfigure(encoding="utf-8")   # ensure_ascii=False: the console's codec must not decide
    sys.stdout.write(render(contract))


if __name__ == "__main__":
    main()
