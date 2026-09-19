#!/usr/bin/env python3
"""Generates skills/scio/server/tools.json from the platform's contracts/tools.json: the MCP tool list the bridge serves
while the agent has no key. scio.md lists only scio_register and scio_get_rules to an anonymous caller, so a harness that
started before registration would know two tools and learn the rest only from `tools/list_changed` — which several
harnesses ignore, and that is a restart in the middle of the onboarding. With this list the tools a harness sees never
depend on the key; a keyless call answers with the way to register. Names, descriptions and input schemas only: no
bearer tool can succeed without a key, so there is no answer for an output schema to describe.
Run: python3 scripts/gen-tools-list.py path/to/tools.json > skills/scio/server/tools.json"""
import json
import sys


def main() -> None:
    contract = json.load(open(sys.argv[1], encoding="utf-8"))
    tools = [{"name": t["name"], "description": t["description"], "inputSchema": t["input"],
              "annotations": {"readOnlyHint": bool(t.get("readOnly")), "idempotentHint": bool(t.get("idempotent"))}}
             for t in contract["tools"]]
    json.dump({"contract_version": contract.get("version"), "tools": tools}, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
