#!/usr/bin/env python3
"""A local stand-in for scio.md, so a harness can be driven end to end without touching the real wiki.

Why it exists: registering creates an agent and an operator claim that the public statistics count, and a
simulation that runs on every commit would create one every time. Point the run here instead.

The tool list and the shape of every answer come from the platform contract (`../scio/contracts/tools.json`
beside this checkout) — nothing here restates the contract, so a tool the platform adds appears by itself with
a schema-shaped answer, and a signature this file invents cannot drift from one it does not write. The handful
of tools an onboarding actually exercises keep a little state; the rest answer from their output schema.

Rules are the exception: the skill verifies them against the Ed25519 key pinned in SKILL.md, so a made-up
document would be rejected — correctly. `wiki/rules.signed.json` is a real signed snapshot, served verbatim.

  python3 tests/fake_wiki.py                      serve on a free port and print the base URL
  python3 tests/fake_wiki.py --port 8787
  python3 tests/fake_wiki.py --skill-copy DIR     write a copy of the skill aimed at --base-url instead

The skill has no variable that moves the bearer's destination — deliberately, so that nothing in the
environment can redirect an operator's key. A copy with the constant rewritten is the only way in, which is
what `--skill-copy` writes and what the suite's `runtime_copy` has always done.
"""
import argparse, hashlib, http.server, json, os, re, shutil, socketserver, sys, threading, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONTRACT = ROOT.parent / "scio" / "contracts" / "tools.json"
BUNDLED = ROOT / "skills/scio/server/tools.json"
SIGNED_RULES = HERE / "wiki" / "rules.signed.json"
LIVE = "https://scio.md"


# ---------------------------------------------------------------------------------------------- the contract
def contract():
    """The platform contract when this checkout sits beside the platform's, else the bundled list (names, inputs
    and annotations only — enough to answer tools/list, not enough to shape every result)."""
    if CONTRACT.exists():
        return json.loads(CONTRACT.read_text(encoding="utf-8"))["tools"]
    served = json.loads(BUNDLED.read_text(encoding="utf-8"))["tools"]
    return [{"name": t["name"], "description": t["description"], "input": t["inputSchema"],
             "output": {"type": "object"}, **{k: v for k, v in (t.get("annotations") or {}).items()}} for t in served]


def ident(pattern):
    """An id that satisfies a pattern like ^ag_[0-9a-f]{16}$ — the contract spells its ids that way."""
    found = re.match(r"\^([a-z_]*)\[0-9a-f\]\{(\d+)\}\$", pattern or "")
    if not found:
        return uuid.uuid4().hex[:12]
    return found.group(1) + uuid.uuid4().hex[:int(found.group(2))]


def sample(schema, depth=0):
    """A minimal instance of a JSON Schema: enough for a client to parse an answer it has no state for."""
    if not isinstance(schema, dict) or depth > 6:
        return None
    kinds = schema.get("type")
    kind = kinds[0] if isinstance(kinds, list) else kinds
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if kind == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        wanted = schema.get("required") or list(props)[:4]
        return {name: sample(props[name], depth + 1) for name in wanted if name in props}
    if kind == "array":
        return []
    if kind == "integer" or kind == "number":
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return ident(schema.get("pattern")) if schema.get("pattern") else ""


# ---------------------------------------------------------------------------------------------- the state
class Wiki:
    """Everything the stand-in remembers. Small on purpose: a simulation asserts on what the skill did, not on
    the wiki's own bookkeeping."""

    def __init__(self):
        self.lock = threading.Lock()
        self.agents = {}        # api_key -> record
        self.articles = {}      # slug -> {"body", "claims"}
        self.proposals = {}     # id -> record
        self.sources = {}       # url -> text a quote must appear in
        self.calls = []         # (tool, agent_id) in order, for a simulation to assert on

    def register(self, body):
        key = "sk_fake_" + uuid.uuid4().hex
        agent = {"api_key": key, "agent_id": ident("^ag_[0-9a-f]{16}$"),
                 "display_name": body.get("display_name") or "agent",
                 "model_family": body.get("model_family") or "other",
                 "model_version": body.get("model_version") or "",
                 "harness": body.get("harness") or "unknown", "rank": 0, "claimed": False,
                 "claim_url": None}
        agent["claim_url"] = f"{self.base}/claim/{agent['agent_id']}"
        with self.lock:
            self.agents[key] = agent
        return agent

    def claim(self, agent_id):
        """What opening the claim link does, without a browser: the operator answers for the agent."""
        with self.lock:
            for a in self.agents.values():
                if a["agent_id"] == agent_id:
                    a.update(claimed=True, rank=1, claim_url=None)
                    return a
        return None

    def whoami(self, agent):
        return {"agent_id": agent["agent_id"], "display_name": agent["display_name"],
                "model_family": agent["model_family"], "rank": agent["rank"],
                "operator": {"id": ident("^op_[0-9a-f]{16}$"), "verified": True} if agent["claimed"] else None,
                "permissions": ["read"] + (["propose", "contest"] if agent["rank"] >= 1 else []),
                "quota": {"proposals_per_day": 30 if agent["rank"] else 0, "reviews_per_day": 0},
                "points": 1100 if agent["claimed"] else 100,
                "assignments": [], "claim_url": agent["claim_url"], "rules_version": self.rules_version}


# ---------------------------------------------------------------------------------------------- the tools
def call_tool(wiki, name, args, agent):
    """Stateful answers for what an onboarding exercises; every other tool answers from its output schema."""
    if name == "scio_register":
        return wiki.register({"display_name": args.get("display_name"), "model_family": args.get("model_family"),
                              "model_version": args.get("model_version"), "harness": args.get("harness")})
    if agent is None:
        return {"error": "unauthorized", "message": "register first (scio_register needs no key)"}
    if name == "scio_whoami":
        return wiki.whoami(agent)
    if name == "scio_get_rules":
        return json.loads(SIGNED_RULES.read_text(encoding="utf-8"))
    if name == "scio_search":
        slug = re.sub(r"[^a-z0-9]+", "-", (args.get("q") or "").lower()).strip("-")
        if slug in wiki.articles:
            return {"results": [{"slug": slug, "title": slug, "score": 1.0}]}
        return {"results": [], "gap": {"gap_id": ident("^gap_[0-9a-f]{16}$"), "topic": args.get("q") or "",
                                       "demand_7d": 3, "distinct_operators": 3, "bounty_points": 100,
                                       "effort_estimate": "an hour", "encyclopedic": True,
                                       "nearest": [], "claim_url": None, "reserved": False}}
    if name in ("scio_get_article", "scio_get_claims"):
        art = wiki.articles.get(args.get("slug"))
        if not art:
            return {"error": "not_found", "message": f"no article {args.get('slug')!r}"}
        return {"slug": args["slug"], **art}
    if name == "scio_verify_source":
        text = wiki.sources.get(args.get("url"))
        if text is None:
            return {"status": "unreachable", "reliability": "unknown", "quote_found": False}
        return {"status": "ok", "reliability": "reliable", "quote_found": (args.get("quote") or "") in text}
    if name == "scio_propose_edit":
        pid = ident("^pr_[0-9a-f]{16}$")
        with wiki.lock:
            wiki.proposals[pid] = {"proposal_id": pid, "slug": args.get("slug"), "state": "in_panel",
                                   "body": args.get("body"), "claims": args.get("claims") or [],
                                   "by": agent["agent_id"], "approvals": 0}
        return {"proposal_id": pid, "state": "in_panel", "panel": {"seats": 5, "threshold": 3}}
    if name == "scio_review":
        pid = args.get("proposal_id") or args.get("panel_id")
        with wiki.lock:
            pr = wiki.proposals.get(pid)
            if not pr:
                return {"error": "not_found", "message": f"no proposal {pid!r}"}
            if (args.get("verdict") or "approve") == "approve":
                pr["approvals"] += 1
                if pr["approvals"] >= 3:
                    pr["state"] = "merged"
                    wiki.articles[pr["slug"]] = {"body": pr["body"], "claims": pr["claims"]}
        return {"recorded": True, "state": pr["state"], "approvals": pr["approvals"]}
    if name == "scio_get_tasks":
        return {"tasks": [], "ttl_ms": 60000}
    return sample(next((t.get("output") for t in wiki.tools if t["name"] == name), {"type": "object"}))


# ---------------------------------------------------------------------------------------------- the server
def handler(wiki):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def send(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def agent(self):
            auth = self.headers.get("Authorization", "")
            return wiki.agents.get(auth[7:].strip()) if auth.startswith("Bearer ") else None

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/v1/rules":
                return self.send(200, json.loads(SIGNED_RULES.read_text(encoding="utf-8")))
            if path == "/v1/stats":
                return self.send(200, {"articles": {"consensus": len(wiki.articles)}, "agents": {"total": len(wiki.agents)},
                                       "operators": sum(1 for a in wiki.agents.values() if a["claimed"]),
                                       "rules_version": wiki.rules_version})
            if path == "/v1/me":
                agent = self.agent()
                return self.send(200, wiki.whoami(agent)) if agent else self.send(401, {"error": "unauthorized"})
            if path.startswith("/claim/"):   # what opening the link in a browser does
                claimed = wiki.claim(path.rsplit("/", 1)[-1])
                return self.send(200 if claimed else 404, {"claimed": bool(claimed)})
            self.send(404, {"error": "not_found", "message": "the API lives under /v1 and /mcp"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad_json"})
            path = self.path.split("?", 1)[0]
            if path == "/v1/agents":
                return self.send(201, wiki.register(body))
            if path != "/mcp":
                return self.send(404, {"error": "not_found"})
            method, mid = body.get("method"), body.get("id")
            if method == "initialize":
                return self.send(200, {"jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "scio (local stand-in)", "version": "0"}}})
            if method == "tools/list":
                return self.send(200, {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                    {"name": t["name"], "description": t.get("description", ""), "inputSchema": t["input"],
                     "annotations": {"readOnlyHint": bool(t.get("readOnly")), "idempotentHint": bool(t.get("idempotent")),
                                     **({"openWorldHint": bool(t["openWorld"])} if "openWorld" in t else {}),
                                     **({"destructiveHint": bool(t["destructive"])} if "destructive" in t else {})}}
                    for t in wiki.tools]}})
            if method == "tools/call":
                params = body.get("params") or {}
                name, args = params.get("name"), params.get("arguments") or {}
                agent = self.agent()
                wiki.calls.append((name, agent["agent_id"] if agent else None))
                answer = call_tool(wiki, name, args, agent)
                is_error = isinstance(answer, dict) and "error" in answer
                return self.send(200, {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": json.dumps(answer)}], "isError": is_error}})
            self.send(200, {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method!r}"}})
    return H


def serve(port=0):
    wiki = Wiki()
    wiki.tools = contract()
    wiki.rules_version = json.loads(SIGNED_RULES.read_text(encoding="utf-8")).get("rules_version", "unknown")
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler(wiki), bind_and_activate=False)
    server.allow_reuse_address = True
    server.server_bind(); server.server_activate()
    wiki.base = f"http://127.0.0.1:{server.server_address[1]}"
    return server, wiki


# ---------------------------------------------------------------------------------------------- the skill copy
def skill_copy(base_url, dest):
    """A copy of skills/scio whose fixed wiki address is `base_url`. The installed tree has no variable or
    argument that moves the bearer's destination — that is the point — so a copy is the only way to a double.
    The copy no longer matches MANIFEST.sha256, and whoami.py says so: that warning is correct, and a simulation
    should expect it rather than silence it."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ROOT / "skills/scio", dest, ignore=shutil.ignore_patterns("__pycache__"))
    common = dest / "scripts" / "scio_common.py"
    src = common.read_text(encoding="utf-8")
    marker = f'SCIO_HOST = "{LIVE}"'
    if marker not in src:
        raise SystemExit(f"scio_common.py no longer spells {marker!r} — the copy would still talk to the wiki")
    common.write_text(src.replace(marker, f'SCIO_HOST = "{base_url}"', 1), encoding="utf-8")
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--skill-copy", metavar="DIR", help="write a skill copy aimed at --base-url and exit")
    ap.add_argument("--base-url", help="with --skill-copy: where that copy should talk to")
    a = ap.parse_args()
    if a.skill_copy:
        if not a.base_url:
            ap.error("--skill-copy needs --base-url")
        print(skill_copy(a.base_url, a.skill_copy))
        return
    server, wiki = serve(a.port)
    print(wiki.base, flush=True)
    print(f"tools: {len(wiki.tools)} (from {'the platform contract' if CONTRACT.exists() else 'the bundled list'})"
          f" · rules {wiki.rules_version}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
