#!/usr/bin/env python3
"""A local stand-in for scio.md, so a harness can be driven end to end without touching the real wiki.

Why it exists: registering creates an agent and an operator claim that the public statistics count, and a
simulation that runs on every commit would create one every time. Point the run here instead.

It is worth having only if a run that passes here would pass against scio.md, so it answers the way the contract
says production answers. The tool list, the `auth` of each tool (none / optional / bearer), the inputs the server
validates and the shape of every answer come from the contract — `wiki/tools.json`, the deployed contract as of the
last release (scripts/sync-contract.py writes it). Every answer is the tool's output schema sampled — required
fields, enums, id patterns, rules_version — with the state written over it, and carries structuredContent beside the
text, as the server's answers do; a refusal is a tool error whose text is `<code>: <detail>`, as the server's
McpException is. The handful of tools an onboarding exercises keep a little state (register, the claim, whoami,
search, source checks, a proposal, its panel, the article it becomes); the rest answer from their output schema.

Rules are the exception: the skill verifies them against the Ed25519 key pinned in SKILL.md, so a made-up
document would be rejected — correctly. `wiki/rules.signed.json` is a real signed snapshot, served verbatim.

  python3 tests/fake_wiki.py                      serve on a free port and print the base URL
  python3 tests/fake_wiki.py --port 8787
  python3 tests/fake_wiki.py --contract PATH      serve another contract (an undeployed one, from a platform checkout)
  python3 tests/fake_wiki.py --two-hints          list readOnlyHint and idempotentHint only: the bridge fills the rest
  python3 tests/fake_wiki.py --skill-copy DIR     write a copy of the skill aimed at --base-url instead

The skill has no variable that moves the bearer's destination — deliberately, so that nothing in the
environment can redirect an operator's key. A copy with the constant rewritten is the only way in, which is
what `--skill-copy` writes and what the suite's `runtime_copy` has always done.
"""
import argparse, hashlib, http.server, json, re, secrets, shutil, socketserver, sys, threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SIGNED_RULES = HERE / "wiki" / "rules.signed.json"
SNAPSHOT = HERE / "wiki" / "tools.json"   # the deployed contract at the last release (scripts/sync-contract.py)
LIVE = "https://scio.md"
PANEL_SEATS, PANEL_THRESHOLD = 5, 3   # the first growth tier (panels.growth.tiers), the one alpha runs in
SEAT_MINUTES = 360                    # … and its seat lifetime

sys.path.insert(0, str(ROOT / "skills/scio/scripts"))
from scio_common import family_from_model   # noqa: E402 — the platform's ModelFamilies.FromModel, as the plugin mirrors it


# ---------------------------------------------------------------------------------------------- the contract
def contract(path=None):
    """The tools of the contract at `path` (default: the release's snapshot)."""
    body = json.loads(Path(path or SNAPSHOT).read_text(encoding="utf-8"))
    return body if isinstance(body, list) else body["tools"]


def now():
    return datetime.now(timezone.utc)


def instant(t):
    """The server's spelling of an instant: UTC, six fraction digits, +00:00."""
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _generate(body):
    """The shortest string the small regex dialect of the contract's patterns accepts — literals, escapes, classes,
    groups with alternatives, quantifiers — with random hex wherever the class is [0-9a-f], so that ids differ."""
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == "(":
            depth, j = 1, i + 1
            while depth:
                depth += {"(": 1, ")": -1}.get(body[j], 0)
                j += 1
            inner = body[i + 1:j - 1]
            depth, cut = 0, len(inner)   # the first alternative at this group's own level
            for k, ch in enumerate(inner):
                depth += {"(": 1, ")": -1}.get(ch, 0)
                if ch == "|" and depth == 0:
                    cut = k
                    break
            unit, i = (lambda text=_generate(inner[:cut]): text), j
        elif c == "[":
            j = body.index("]", i + 1)
            cls = body[i + 1:j]
            unit = (lambda: secrets.token_hex(1)[0]) if cls == "0-9a-f" else (lambda first=cls.lstrip("^")[0]: first)
            i = j + 1
        elif c == "\\":
            unit, i = (lambda ch=body[i + 1]: {"S": "x", "d": "0", "w": "x"}.get(ch, ch)), i + 2
        else:
            unit, i = (lambda ch=c: ch), i + 1
        times = 1
        quant = re.match(r"\{(\d+)(?:,\d*)?\}|[*?+]", body[i:])
        if quant:
            times = int(quant.group(1)) if quant.group(1) else {"*": 0, "?": 0, "+": 1}[quant.group(0)]
            i += len(quant.group(0))
        out += [unit() for _ in range(times)]
    return "".join(out)


def ident(pattern):
    """A value that satisfies a pattern: ^ag_[0-9a-f]{16}$ and ^(pr|ds)_[0-9a-f]{16}$ (the contract spells its ids that
    way), ^media:[0-9a-f]{64}\\.(svg|png|jpg|webp)$, a BCP-47 tag… — random hex where the pattern asks for hex."""
    body = (pattern or "").lstrip("^").rstrip("$")
    try:
        made = _generate(body)
        if re.search(pattern, made):
            return made
    except (ValueError, IndexError, KeyError, re.error):
        pass
    return secrets.token_hex(6)


def sample(schema, depth=0):
    """A minimal instance of a JSON Schema — its required fields, each of the right type, enum, pattern and format —
    enough for a client to parse an answer the stand-in keeps no state for."""
    if not isinstance(schema, dict) or depth > 8:
        return None
    kinds = schema.get("type")
    kind = kinds[0] if isinstance(kinds, list) else kinds
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if kind == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        return {name: sample(props[name], depth + 1) for name in schema.get("required") or [] if name in props}
    if kind == "array":
        return [sample(schema.get("items"), depth + 1) for _ in range(schema.get("minItems", 0))]
    if kind in ("integer", "number"):
        return schema.get("minimum", 0)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    if schema.get("format") == "date-time":
        return instant(now())
    if schema.get("format") == "uri":
        return LIVE + "/"
    if schema.get("pattern"):
        return ident(schema["pattern"])
    return "x" * schema.get("minLength", 0)


def overlay(base, extra):
    """`base` (a sample of the output schema) with the stand-in's state written over it, dicts merged key by key."""
    if isinstance(base, dict) and isinstance(extra, dict):
        out = dict(base)
        for k, v in extra.items():
            out[k] = overlay(base.get(k), v)
        return out
    return extra


def refused(schema, args):
    """What the server's validators refuse in the top-level arguments — required fields, unknown fields, types, enums,
    lengths, patterns, counts, ranges — as its `validation_failed` text; "" when nothing is wrong. Nested values are
    left to the gates."""
    problems = []
    props = schema.get("properties") or {}
    for name in schema.get("required") or []:
        if args.get(name) in (None, "", [], {}):
            problems.append(f"{name} must not be empty")
    if schema.get("additionalProperties") is False:
        problems += [f"{name} is not an input of this tool" for name in args if name not in props]
    kinds = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    for name, value in args.items():
        s = props.get(name)
        if not isinstance(s, dict) or value is None:
            continue
        wanted = s.get("type")
        if isinstance(wanted, str) and wanted in kinds and (not isinstance(value, kinds[wanted]) or
                                                             (wanted in ("integer", "number") and isinstance(value, bool))):
            problems.append(f"{name} must be {wanted}")
            continue
        if s.get("enum") and value not in s["enum"]:
            problems.append(f"{name} must be one of: {', '.join(map(str, s['enum']))}")
        if isinstance(value, str):
            if len(value) > s.get("maxLength", 1 << 30) or (value and len(value) < s.get("minLength", 0)):
                problems.append(f"{name} length outside {s.get('minLength', 0)}–{s.get('maxLength', '∞')}")
            if s.get("pattern") and value and not re.search(s["pattern"], value):
                problems.append(f"{name} does not match {s['pattern']}")
        if isinstance(value, list) and not (s.get("minItems", 0) <= len(value) <= s.get("maxItems", 1 << 30)):
            problems.append(f"{name} must have {s.get('minItems', 0)}–{s.get('maxItems', '∞')} items")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not (
                s.get("minimum", float("-inf")) <= value <= s.get("maximum", float("inf"))):
            problems.append(f"{name} out of range")
    return "validation_failed: " + "; ".join(problems) if problems else ""


class Refusal(Exception):
    """A business refusal: the server answers it as a tool error whose text is `<code>: <detail>`."""


# ---------------------------------------------------------------------------------------------- the state
class Wiki:
    """Everything the stand-in remembers. Small on purpose: a simulation asserts on what the skill did, not on
    the wiki's own bookkeeping."""

    def __init__(self):
        self.lock = threading.RLock()
        self.agents = {}        # api_key -> record
        self.articles = {}      # slug -> the article as scio_get_article answers it
        self.pages = {}         # slug -> page id, for search
        self.proposals = {}     # id -> record
        self.panels = {}        # id -> {"proposal", "seats": {agent_id: seat}, "approvals", "open"}
        self.sources = {}       # url -> text a quote must appear in
        self.calls = []         # (tool, agent_id) in order, tools/list included, for a simulation to assert on
        self.hints = 4          # annotations listed per tool: four as scio.md sends them, or two (--two-hints)
        self.tools = []
        self.rules_version = "unknown"
        self.base = ""

    def tool(self, name):
        return next((t for t in self.tools if t["name"] == name), None)

    def answer(self, name, state):
        """The tool's output schema, sampled, with `state` over it and the rules version the server stamps on answers."""
        schema = (self.tool(name) or {}).get("output") or {"type": "object"}
        if "rules_version" in (schema.get("properties") or {}):
            state = dict(state, rules_version=self.rules_version)
        return overlay(sample(schema), state)

    # --- identity
    def register(self, args):
        problem = refused((self.tool("scio_register") or {}).get("input") or {}, args)
        if problem:
            raise Refusal(problem)
        named = family_from_model(args.get("model_version"))   # the model id outranks the declared family (19 Sep 2026)
        token = secrets.token_urlsafe(24)   # the link carries a secret token, never the agent id (BP-01)
        agent = {"api_key": "sk_live_" + secrets.token_hex(20), "agent_id": ident("^ag_[0-9a-f]{16}$"),
                 "display_name": args["display_name"], "model_family": named if named != "other" else args["model_family"],
                 "model_version": args.get("model_version") or "", "harness": args.get("harness") or "unknown",
                 "rank": 0, "operator": None, "token": token, "claim_url": f"{self.base}/claim/{token}", "points": 100}
        with self.lock:
            self.agents[agent["api_key"]] = agent
        receipt = {k: agent[k] for k in ("agent_id", "api_key", "claim_url", "rank", "model_family", "points")}
        receipt["key_prefix"] = agent["api_key"][:12]
        return self.answer("scio_register", receipt)

    def claim(self, token):
        """What opening the claim link does, without a browser: the operator answers for the agent."""
        with self.lock:
            for a in self.agents.values():
                if a["token"] and secrets.compare_digest(a["token"], token):
                    a.update(rank=1, token=None, claim_url=None, operator=ident("^op_[0-9a-f]{16}$"), points=a["points"] + 1000)
                    return a
        return None

    def seats_of(self, agent):
        with self.lock:
            return [(pid, p["seats"][agent["agent_id"]]) for pid, p in self.panels.items()
                    if p["open"] and agent["agent_id"] in p["seats"] and not p["seats"][agent["agent_id"]]["verdict"]]

    def whoami(self, agent):
        claimed = agent["rank"] >= 1
        return self.answer("scio_whoami", {
            "agent_id": agent["agent_id"], "display_name": agent["display_name"], "model_family": agent["model_family"],
            "rank": agent["rank"], "operator": {"id": agent["operator"], "verified": True} if claimed else None,
            "permissions": ["read"] + (["propose", "review_small", "review_article", "contest"] if claimed else []),
            "quota": {"proposals_left_today": 30 if claimed else 0, "reviews_left_today": 100 if claimed else 0,
                      "points_balance": agent["points"], "verifications_left_today": 50 if claimed else 10},
            "assignments": [{"panel_id": pid, "proposal_id": self.panels[pid]["proposal"], "kind": "article",
                             "expires_at": seat["expires_at"]} for pid, seat in self.seats_of(agent)],
            "claim_url": agent["claim_url"], "languages": [], "languages_declared": []})

    # --- reading
    def search(self, args):
        query = args["query"]
        words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
        with self.lock:
            hits = [a for a in self.articles.values()
                    if words and all(w in (a["slug"] + " " + a["title"]).lower() for w in words)]
        if hits:
            return self.answer("scio_search", {"gap": None, "results": [
                {"id": self.pages[a["slug"]], "slug": a["slug"], "title": a["title"], "lang": a["lang"], "state": a["state"],
                 "summary": a["front_matter"]["summary"]} for a in hits[:args.get("limit") or 10]]})
        return self.answer("scio_search", {"results": [], "gap": {
            "gap_id": ident("^gp_[0-9a-f]{16}$"), "topic": query, "lang": args.get("lang") or "en", "encyclopedic": True,
            "source": "search", "demand_7d": 1, "distinct_operators": 1, "bounty_points": 100, "claim_url": None}})

    def article(self, args):
        with self.lock:
            found = self.articles.get(args["slug"])
        if not found:
            raise Refusal("not_found")
        return found

    # --- writing
    def verify_source(self, args):
        url, quote = args["url"], args.get("quote")
        text = self.sources.get(url)
        if text is None:   # nothing registered for the URL: a page that does not answer
            return self.answer("scio_verify_source", {"status": "dead", "quote_found": None, "match_score": None,
                                                      "source_class": "secondary", "reliability": "unknown"})
        found = None if quote is None else quote in text
        return self.answer("scio_verify_source", {
            "status": "live", "quote_found": found, "match_score": None if found is None else (1.0 if found else 0.0),
            "source_class": "secondary", "reliability": "unknown", "extracted_text_preview": text[:500],
            "snapshot_id": ident("^sn_[0-9a-f]{16}$"), "from_snapshot": False})

    def propose(self, agent, args):
        if agent["rank"] < 1:
            raise Refusal('permission_denied: {"required_rank": 1, "how_to_earn": "get claimed by your operator (claim_url)"}')
        pid, panel = ident("^pr_[0-9a-f]{16}$"), ident("^pn_[0-9a-f]{16}$")
        with self.lock:
            self.proposals[pid] = dict(args, proposal_id=pid, author=agent["agent_id"], panel=panel, state="in_panel")
            self.panels[panel] = {"proposal": pid, "seats": {}, "approvals": 0, "open": True}
        return self.answer("scio_propose_edit", {"proposal_id": pid, "state": "in_panel", "quota_left_today": 29})

    def tasks(self, agent):
        """Seats first: an open panel the agent did not write and has no seat on draws it, up to the panel's size."""
        if agent["rank"] >= 1:
            with self.lock:
                for p in self.panels.values():
                    if (p["open"] and agent["agent_id"] not in p["seats"] and len(p["seats"]) < PANEL_SEATS
                            and self.proposals[p["proposal"]]["author"] != agent["agent_id"]):
                        p["seats"][agent["agent_id"]] = {"seat_no": len(p["seats"]) + 1, "verdict": None,
                                                         "expires_at": instant(now() + timedelta(minutes=SEAT_MINUTES))}
        hour = instant(now().replace(minute=0, second=0, microsecond=0))
        tasks = [{"task_id": ident("^tk_[0-9a-f]{16}$"), "kind": "panel_seat", "ref_kind": "panel", "ref_id": pid,
                  "title": "Review an article proposal", "lang": "en", "expires_at": seat["expires_at"], "ttl_ms": 600000}
                 for pid, seat in self.seats_of(agent)][:5]
        return self.answer("scio_get_tasks", {"tasks": tasks, "hour": hour, "ttl_ms": 600000,
                                              "seed": hashlib.sha256(f"{agent['agent_id']}|{hour}".encode()).hexdigest()})

    def seat(self, agent, panel_id):
        with self.lock:
            panel = self.panels.get(panel_id)
            seat = panel["seats"].get(agent["agent_id"]) if panel and panel["open"] else None
        if not seat or seat["verdict"]:
            raise Refusal('assignment_expired: {"reason": "seat_expired"}')
        return panel, seat

    def panel(self, agent, args):
        panel, seat = self.seat(agent, args["panel_id"])
        pr = self.proposals[panel["proposal"]]
        return self.answer("scio_get_panel", {
            "panel_id": args["panel_id"], "seat_no": seat["seat_no"], "expires_at": seat["expires_at"], "kind": pr["kind"],
            "lang": pr["lang"], "summary": pr["summary"], "body": pr.get("body"), "diff": None, "media": [], "gate_flags": [],
            "claims": [{"ordinal": c.get("ordinal", i + 1), "text": c.get("text", ""), "kind": c.get("kind", "sourced"),
                        "source_url": c.get("source_url", LIVE + "/"), "quote": c.get("quote", ""), "disputed": False}
                       for i, c in enumerate(pr["claims"]) if isinstance(c, dict)]})

    def review(self, agent, args):
        panel, seat = self.seat(agent, args["panel_id"])
        with self.lock:
            seat["verdict"] = args["verdict"]
            if args["verdict"] == "approve":
                panel["approvals"] += 1
            if panel["approvals"] >= PANEL_THRESHOLD:
                panel["open"] = False
                self.merge(self.proposals[panel["proposal"]])
            agent["points"] += 10
        return self.answer("scio_review", {"accepted": True, "seat_no": seat["seat_no"], "points_earned": 10,
                                           "panel_closes_at": seat["expires_at"] if panel["open"] else None})

    def merge(self, pr):
        body = pr.get("body") or ""
        author = next(a for a in self.agents.values() if a["agent_id"] == pr["author"])
        claims = [{"id": ident("^cl_[0-9a-f]{16}$"), "ordinal": c.get("ordinal", i + 1), "text": c.get("text", ""),
                   "kind": c.get("kind", "sourced"), "state": "supported", "quote": c.get("quote", ""),
                   "source": {"url": c.get("source_url", LIVE + "/"), "class": "secondary", "reliability": "unknown"},
                   "agent": author["agent_id"], "model_family": author["model_family"]}
                  for i, c in enumerate(pr["claims"]) if isinstance(c, dict)]
        pr["state"] = "merged"
        self.pages.setdefault(pr["slug"], ident("^pg_[0-9a-f]{16}$"))
        self.articles[pr["slug"]] = self.answer("scio_get_article", {
            "slug": pr["slug"], "lang": pr["lang"], "title": pr["slug"].replace("-", " ").title(), "state": "consensus",
            "revision_id": ident("^rv_[0-9a-f]{16}$"), "body_hash": hashlib.sha256(body.encode()).hexdigest(),
            "front_matter": {"summary": pr["summary"], "lang": pr["lang"]}, "body": body, "claims": claims})


# ---------------------------------------------------------------------------------------------- the tools
def call_tool(wiki, name, args, agent, presented_key=""):
    """One tools/call, as the server answers it: the answer, or a Refusal. The tool's `auth` decides who may call."""
    tool = wiki.tool(name)
    if tool is None:
        raise Refusal(f"not_found: no tool {name!r}")
    auth = tool.get("auth", "bearer")
    if presented_key and agent is None and auth != "none":
        raise Refusal("unauthenticated: the key sent does not authenticate — register, or ask your operator")
    if auth == "bearer" and agent is None:
        raise Refusal("unauthenticated: send Authorization: Bearer sk_…")
    if name == "scio_register":
        return wiki.register(args)
    problem = refused(tool.get("input") or {}, args)
    if problem:
        raise Refusal(problem)
    if name == "scio_get_rules":
        return json.loads(SIGNED_RULES.read_text(encoding="utf-8"))
    if name == "scio_whoami":
        return wiki.whoami(agent)
    if name == "scio_search":
        return wiki.search(args)
    if name == "scio_get_article":
        return wiki.article(args)
    if name == "scio_get_claims":
        found = wiki.article(args)
        return wiki.answer("scio_get_claims", {"revision_id": found["revision_id"], "claims": found["claims"]})
    if name == "scio_verify_source":
        return wiki.verify_source(args)
    if name == "scio_propose_edit":
        return wiki.propose(agent, args)
    if name == "scio_get_tasks":
        return wiki.tasks(agent)
    if name == "scio_get_panel":
        return wiki.panel(agent, args)
    if name == "scio_review":
        return wiki.review(agent, args)
    return wiki.answer(name, {})


def listed(wiki):
    """tools/list: the contract's tools with their annotations — four, as scio.md sends them, or two (--two-hints)."""
    out = []
    for t in wiki.tools:
        hints = {"readOnlyHint": bool(t.get("readOnly")), "idempotentHint": bool(t.get("idempotent"))}
        if wiki.hints == 4:
            hints.update({hint: bool(t[field]) for hint, field in (("openWorldHint", "openWorld"), ("destructiveHint", "destructive"))
                          if field in t})
        out.append({"name": t["name"], "description": t.get("description", ""), "inputSchema": t["input"], "annotations": hints})
    return out


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

        def key(self):
            auth = self.headers.get("Authorization", "")
            return auth[7:].strip() if auth.startswith("Bearer ") else ""

        def agent(self):
            return wiki.agents.get(self.key())

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/v1/rules":
                return self.send(200, json.loads(SIGNED_RULES.read_text(encoding="utf-8")))
            if path == "/v1/tools.json":
                return self.send(200, {"tools": wiki.tools})
            if path == "/v1/stats":
                return self.send(200, {"articles": {"consensus": len(wiki.articles)}, "agents": {"total": len(wiki.agents)},
                                       "operators": sum(1 for a in wiki.agents.values() if a["rank"] >= 1),
                                       "rules_version": wiki.rules_version})
            if path == "/v1/me":
                agent = self.agent()
                return self.send(200, wiki.whoami(agent)) if agent else self.send(401, {"error": "unauthenticated"})
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
            if not isinstance(body, dict):
                return self.send(400, {"error": "bad_json"})
            path = self.path.split("?", 1)[0]
            if path == "/v1/agents":
                try:
                    return self.send(201, wiki.register(body))
                except Refusal as e:
                    return self.send(400, {"error": str(e).split(":", 1)[0], "message": str(e)})
            if path != "/mcp":
                return self.send(404, {"error": "not_found"})
            method, mid = body.get("method"), body.get("id")
            agent = self.agent()
            if method == "initialize":
                return self.send(200, {"jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "scio (local stand-in)", "version": "0"}}})
            if method == "tools/list":
                wiki.calls.append(("tools/list", agent["agent_id"] if agent else None))
                return self.send(200, {"jsonrpc": "2.0", "id": mid, "result": {"tools": listed(wiki)}})
            if method == "tools/call":
                params = body.get("params") or {}
                name, args = params.get("name"), params.get("arguments") or {}
                wiki.calls.append((name, agent["agent_id"] if agent else None))
                try:
                    answer = call_tool(wiki, name, args if isinstance(args, dict) else {}, agent, self.key())
                    result = {"content": [{"type": "text", "text": json.dumps(answer)}], "structuredContent": answer, "isError": False}
                except Refusal as e:   # the server's McpException: a tool error, its code and detail as the text
                    result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
                return self.send(200, {"jsonrpc": "2.0", "id": mid, "result": result})
            self.send(200, {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method!r}"}})
    return H


def serve(port=0, contract_path=None, hints=4):
    wiki = Wiki()
    wiki.tools = contract(contract_path)
    wiki.hints = hints
    wiki.rules_version = json.loads(SIGNED_RULES.read_text(encoding="utf-8")).get("rules_version", "unknown")
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler(wiki), bind_and_activate=False)
    server.allow_reuse_address = True
    server.daemon_threads = True
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
    shutil.copytree(ROOT / "skills/scio", dest, ignore=shutil.ignore_patterns("__pycache__", ".scio"))
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
    ap.add_argument("--contract", metavar="PATH", help="the contract to serve (default tests/wiki/tools.json)")
    ap.add_argument("--two-hints", action="store_true", help="list two annotations per tool; the bridge must fill the rest")
    ap.add_argument("--skill-copy", metavar="DIR", help="write a skill copy aimed at --base-url and exit")
    ap.add_argument("--base-url", help="with --skill-copy: where that copy should talk to")
    a = ap.parse_args()
    if a.skill_copy:
        if not a.base_url:
            ap.error("--skill-copy needs --base-url")
        print(skill_copy(a.base_url, a.skill_copy))
        return
    server, wiki = serve(a.port, a.contract, 2 if a.two_hints else 4)
    print(wiki.base, flush=True)
    print(f"tools: {len(wiki.tools)} (from {a.contract or SNAPSHOT}) · rules {wiki.rules_version}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
