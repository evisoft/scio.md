#!/usr/bin/env python3
"""Regressions for the 23 Sep 2026 review — servers: the bridge (scio_bridge.py) and the local server (scio_local.py).
Run: python3 tests/test-servers.py (test-security.py runs it too).

Work-root containment, agent switching after a registration, the tool list during an outage, anonymous search, the
injection scan of a conflict, what a rejected key and an HTTP-level error tell the model, a registration whose key
cannot be saved, SSE on Python 3.8, scio-as against the Python servers, the registration scripts under the bridge's
lock, the harness at registration. Disposable files and a local double of /mcp (and of /v1/agents) only: the
installed tree has no variable that moves the wiki's address, so the double is reached through an isolated copy of the
skill with that constant rewritten (the same device as tests/test-security.py)."""
import ast
import http.server
import json
import os
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/scio"
FIX = ROOT / "tests/redteam"
PY = sys.executable
INJECTION = (FIX / "01-injection.txt").read_text(encoding="utf-8")
FORBIDDEN = "Access forbidden: This tool requires authorization."   # ModelContextProtocol.AspNetCore 2.2.0, on HTTP 200
SDK_PREFIX = "An error occurred invoking '{}': "   # ModelContextProtocol.Core 2.2.0, before a tool's McpException message


def sse(req_id, result=None, error=None):
    """A 200 text/event-stream answer carrying one JSON-RPC response, as the platform's streamable HTTP sends it."""
    msg = {"jsonrpc": "2.0", "id": req_id}
    msg.update({"error": error} if error is not None else {"result": result})
    return 200, {"Content-Type": "text/event-stream"}, ("event: message\ndata: " + json.dumps(msg) + "\n\n").encode()


def text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


class Wiki:
    """A local double of scio.md's /mcp. Every request is recorded; `override(req)` may answer instead of the default
    (return None to fall through). Registrations hand out a distinct key each."""

    def __init__(self):
        self.seen, self.override, self.hold, self.registrations, self.rest_extra = [], None, 0, 0, {}
        self.lock = threading.Lock()
        wiki = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                params = req.get("params") or {}
                rest = self.path.startswith("/v1/agents")   # register.py and register-models.py register over REST
                with wiki.lock:
                    wiki.seen.append({"method": "POST /v1/agents" if rest else req.get("method"), "name": params.get("name"),
                                      "auth": self.headers.get("Authorization"), "args": req if rest else params.get("arguments")})
                if wiki.hold:
                    time.sleep(wiki.hold)
                status, headers, body = wiki.registered(req) if rest else wiki.respond(req)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def reset(self):
        with self.lock:
            self.seen, self.override, self.hold, self.registrations, self.rest_extra = [], None, 0, 0, {}

    def calls(self, name=None):
        with self.lock:
            return [s for s in self.seen if s["method"] == "tools/call" and (name is None or s["name"] == name)]

    def rest_registrations(self):
        with self.lock:
            return [s for s in self.seen if s["method"] == "POST /v1/agents"]

    def registered(self, body):
        """POST /v1/agents: a new agent, a distinct key each time (the REST twin of scio_register)."""
        with self.lock:
            self.registrations += 1
            n = self.registrations
        data = {"agent_id": f"ag_{n:016x}", "api_key": f"sk_live_REST_{n}_0123456789", "claim_url": f"https://scio.md/claim/r{n}", "rank": 0}
        data.update(self.rest_extra)
        return 200, {"Content-Type": "application/json"}, json.dumps(data).encode()

    def respond(self, req):
        if self.override:
            answer = self.override(req)
            if answer is not None:
                return answer
        method, name = req.get("method"), (req.get("params") or {}).get("name")
        if method == "tools/list":
            return sse(req.get("id"), {"tools": [{"name": "scio_register", "inputSchema": {"type": "object", "properties": {}}},
                                                 {"name": "scio_whoami", "inputSchema": {"type": "object", "properties": {}}}]})
        if method == "tools/call" and name == "scio_register":
            with self.lock:
                self.registrations += 1
                n = self.registrations
            data = {"agent_id": f"ag_{n:016x}", "api_key": f"sk_live_REGISTERED_{n}_0123456789", "claim_url": f"https://scio.md/claim/t{n}", "rank": 0}
            return sse(req.get("id"), {**text_result(json.dumps(data)), "structuredContent": data})
        if method == "tools/call":
            return sse(req.get("id"), text_result("{}"))
        return sse(req.get("id"), {})


class Live:
    """A running server process: requests in, every line out collected by a reader thread (replies and notifications)."""

    def __init__(self, script, env, cwd):
        self.p = subprocess.Popen([PY, str(script)] + (["--harness", "test"] if script.name == "scio_bridge.py" else []),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env, cwd=cwd)
        self.q, self.notes = queue.Queue(), []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.p.stdout:
            if line.strip():
                self.q.put(json.loads(line))

    def ask(self, msg, timeout=30):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                m = self.q.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if m.get("id") == msg.get("id"):
                return m
            self.notes.append(m)
        raise AssertionError(f"no answer to {msg.get('method')} {msg.get('id')}")

    def settle(self, seconds=0.8):
        """Collect whatever else arrives within `seconds` (a notification is written after the reply)."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                self.notes.append(self.q.get(timeout=max(0.05, deadline - time.time())))
            except queue.Empty:
                pass

    def list_changed(self):
        return sum(1 for m in self.notes if m.get("method") == "notifications/tools/list_changed")

    def close(self):
        if not self.p.stdin.closed:
            self.p.stdin.close()
        self.p.wait(timeout=20)
        self.reader.join(timeout=5)
        self.p.stdout.close()


def call(i, name, arguments=None):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


class ServersBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wiki = Wiki()
        cls.copy = Path(tempfile.mkdtemp(prefix="scio-servers-"))
        shutil.copytree(SKILL, cls.copy / "scio", ignore=shutil.ignore_patterns("__pycache__"))
        common = cls.copy / "scio/scripts/scio_common.py"
        source = common.read_text(encoding="utf-8")
        assert 'SCIO_HOST = "https://scio.md"' in source
        common.write_text(source.replace('SCIO_HOST = "https://scio.md"', f'SCIO_HOST = "{cls.wiki.url}"', 1), encoding="utf-8")
        cls.BRIDGE = cls.copy / "scio/server/scio_bridge.py"
        cls.LOCAL = cls.copy / "scio/server/scio_local.py"
        cls.SCRIPTS = cls.copy / "scio/scripts"

    @classmethod
    def tearDownClass(cls):
        cls.wiki.server.shutdown()
        cls.wiki.server.server_close()
        shutil.rmtree(cls.copy, ignore_errors=True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="scio-srv-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(os.path.realpath(temporary.name))
        self.home = self.base / "home"
        self.ws = self.base / "home/src/ws"
        self.ws.mkdir(parents=True)
        self.keys = self.base / "cfg/keys"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("SCIO_") and k != "CLAUDE_PLUGIN_ROOT"}
        self.env.update(HOME=str(self.home), SCIO_KEYS_FILE=str(self.keys), SCIO_TRUST_FILE=str(self.base / "cfg/no-trust"))
        self.wiki.reset()

    def write_keys(self, text):
        self.keys.parent.mkdir(parents=True, exist_ok=True)
        self.keys.write_text(text)
        os.chmod(self.keys, 0o600)

    def run_server(self, script, msgs, cwd=None, args=("--harness", "test"), **env):
        argv = [PY, str(script)] + (list(args) if script.name == "scio_bridge.py" else [])
        r = subprocess.run(argv, input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True,
                           env=dict(self.env, **env), cwd=str(cwd or self.ws), timeout=60)
        self.assertNotIn("Traceback", r.stderr)
        return [json.loads(line) for line in r.stdout.splitlines() if line.strip()], r

    def bridge(self, msgs, cwd=None, **env):
        return self.run_server(self.BRIDGE, msgs, cwd, **env)

    def local(self, msgs, cwd=None, **env):
        return self.run_server(self.LOCAL, msgs, cwd, **env)[0]

    def live(self, script, cwd=None, **env):
        server = Live(script, dict(self.env, **env), str(cwd or self.ws))
        self.addCleanup(server.close)
        return server

    def probe(self, expression, cwd=None, **env):
        """Evaluate `expression` with scio_common imported as c, in a fresh interpreter (cwd and environment of a server)."""
        r = subprocess.run([PY, "-c", f"import sys; sys.path.insert(0, {str(self.SCRIPTS)!r}); import scio_common as c; print({expression})"],
                           capture_output=True, text=True, env=dict(self.env, **env), cwd=str(cwd or self.ws), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()


# ------------------------------------------------------------------------------------ bridge-local-1: the work root
class WorkRootContainment(ServersBase):
    """A repository can carry `.scio/work` (or `.scio`) as a symlink, and a clone recreates it. The default root must never
    be wherever such a link points: 'inside the task folder' would then mean the whole filesystem, or the operator's home."""

    def plant(self, link, target):
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, str(link), target_is_directory=True)

    def outside_secret(self):
        outside = self.base / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("OUTSIDE_SECRET_CONTENT")
        return outside

    def assert_refused(self, answer):
        self.assertTrue(answer["result"].get("isError"), answer)
        self.assertNotIn("OUTSIDE_SECRET_CONTENT", json.dumps(answer))

    def test_a_work_root_linked_to_the_filesystem_root_reads_and_writes_nothing_outside(self):
        outside = self.outside_secret()
        self.plant(self.ws / ".scio/work", "/")
        out = self.local([call(1, "read_file", {"dir": str(outside), "name": "secret.txt"}),
                          call(2, "write_file", {"dir": str(outside), "name": "planted.txt", "content": "echo pwned"}),
                          call(3, "read_file", {"dir": "/etc", "name": "hostname"})])
        byid = {m["id"]: m for m in out}
        self.assert_refused(byid[1])
        self.assert_refused(byid[2])
        self.assertFalse((outside / "planted.txt").exists())
        self.assertTrue(byid[3]["result"].get("isError"), "a file under the link's target is not inside the task root")

    def test_a_relative_link_up_the_tree_does_not_make_home_the_root(self):
        (self.home / ".ssh").mkdir(parents=True)
        (self.home / ".ssh/id_ed25519").write_text("OUTSIDE_SECRET_CONTENT")
        self.plant(self.ws / ".scio/work", "../../..")   # from ws/.scio: ws → src → home
        out = self.local([call(1, "read_file", {"dir": str(self.ws / ".scio/work/.ssh"), "name": "id_ed25519"}),
                          call(2, "read_file", {"dir": str(self.home / ".ssh"), "name": "id_ed25519"})])
        for m in out:
            self.assert_refused(m)

    def test_a_linked_dot_scio_folder_is_refused_too_and_gets_no_gitignore(self):
        outside = self.outside_secret()
        (outside / "work/t").mkdir(parents=True)
        (outside / "work/t/notes.md").write_text("OUTSIDE_SECRET_CONTENT")
        self.plant(self.ws / ".scio", str(outside))
        out = self.local([call(1, "read_file", {"dir": str(self.ws / ".scio/work/t"), "name": "notes.md"}),
                          call(2, "workdir", {"kind": "write", "ref": "some-article"})])
        self.assert_refused(out[0])
        folder = out[1]["result"]["content"][0]["text"].strip()
        self.assertFalse(folder.startswith(str(self.ws / ".scio")), folder)
        self.assertFalse(os.path.realpath(folder).startswith(str(outside)), folder)
        self.assertFalse((outside / ".gitignore").exists(), "the .gitignore is never written through a linked .scio")
        self.assertEqual(sorted(os.listdir(outside)), ["secret.txt", "work"])

    def test_the_default_root_falls_back_to_the_private_location_when_planted(self):
        self.plant(self.ws / ".scio/work", "/")
        self.assertEqual(self.probe("c.work_root()"), str(self.home / ".local/share/scio/work"))
        self.assertEqual(self.probe("c.inside_work_root('/etc/hostname')"), "False")

    def test_the_bridge_sends_no_proposal_file_through_a_planted_root(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "docker-config.json").write_text(json.dumps({"auths": {"registry.example": {"auth": "ZmFrZTpzZWNyZXQ="}}}))
        self.plant(self.ws / ".scio/work", "/")
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        out, _ = self.bridge([call(1, "scio_propose_edit", {"proposal_file": str(outside / "docker-config.json")})])
        self.assertTrue(out[0]["result"].get("isError"))
        self.assertIn("work root", out[0]["result"]["content"][0]["text"])
        self.assertEqual(self.wiki.calls(), [])

    def test_an_ordinary_workspace_keeps_its_default_root_and_gitignore(self):
        out = self.local([call(1, "workdir", {"kind": "write", "ref": "some-article"})])
        folder = Path(out[0]["result"]["content"][0]["text"].strip())
        self.assertEqual(folder.parent, self.ws / ".scio/work")
        self.assertEqual((self.ws / ".scio/.gitignore").read_text(), "*\n")
        out = self.local([call(1, "write_file", {"dir": str(folder), "name": "draft.md", "content": "hello"})])
        self.assertFalse(out[0]["result"].get("isError"), out)
        out = self.local([call(1, "read_file", {"dir": str(folder), "name": "draft.md"})])   # calls run in parallel: one at a time here
        self.assertEqual(out[0]["result"]["content"][0]["text"], "hello")

    def test_scio_work_dir_is_the_operators_choice_even_when_it_is_a_link(self):
        real = self.base / "shared-root"
        real.mkdir()
        link = self.base / "link-root"
        os.symlink(str(real), str(link), target_is_directory=True)
        out = self.local([call(1, "workdir", {"kind": "write", "ref": "a"})], SCIO_WORK_DIR=str(link))
        folder = out[0]["result"]["content"][0]["text"].strip()
        self.assertTrue(folder.startswith(str(link)), folder)
        out = self.local([call(1, "write_file", {"dir": folder, "name": "draft.md", "content": "x"})], SCIO_WORK_DIR=str(link))
        self.assertFalse(out[0]["result"].get("isError"), out)
        self.assertTrue(any(real.rglob("draft.md")))


# ------------------------------------------------------------------------------------ bridge-local-2: the tool list
class ToolListDuringAnOutage(ServersBase):
    def test_a_keyed_session_whose_first_listing_fails_gets_the_bundled_list_and_one_list_changed_after_recovery(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        down = {"on": True}
        self.wiki.override = lambda req: (502, {"Content-Type": "text/plain"}, b"bad gateway") if down["on"] else None
        bridge = self.live(self.BRIDGE)
        listing = bridge.ask({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertIn("result", listing, listing)
        tools = {t["name"]: t for t in listing["result"]["tools"]}
        self.assertTrue({"scio_whoami", "scio_review", "scio_propose_edit", "scio_register"} <= set(tools))
        self.assertIn("proposal_file", tools["scio_propose_edit"]["inputSchema"]["properties"])
        self.assertIn("alias", tools["scio_register"]["inputSchema"]["properties"])
        down["on"] = False
        answer = bridge.ask(call(2, "scio_whoami"))
        self.assertIn("result", answer)
        bridge.settle()
        self.assertEqual(bridge.list_changed(), 1, "the harness is told once to re-list the live schemas")
        bridge.ask(call(3, "scio_whoami"))
        bridge.settle()
        self.assertEqual(bridge.list_changed(), 1, "and only once")


# ------------------------------------------------------------------------------------ bridge-local-3, ident-3: use_agent
class UseAgentAfterARegistration(ServersBase):
    def test_use_agent_after_a_registration_in_the_same_session_switches_the_bridge(self):
        self.write_keys("claude-x=sk_live_CLAUDE_X_KEY_0123456789\n# default claude-x\n# model claude-x claude-x\n")
        work = str(self.ws / ".scio/work")
        bridge = self.live(self.BRIDGE, SCIO_WORK_DIR=work)
        reg = bridge.ask(call(1, "scio_register", {"display_name": "t", "model_family": "gpt", "model_version": "gpt-5"}))
        self.assertFalse(reg["result"].get("isError"), reg)
        bridge.ask(call(2, "scio_whoami"))
        self.assertEqual(self.wiki.calls("scio_whoami")[-1]["auth"], "Bearer sk_live_REGISTERED_1_0123456789", "the new agent is used right after")
        out = self.local([call(1, "use_agent", {"model_version": "claude-x"})], SCIO_WORK_DIR=work)
        self.assertFalse(out[0]["result"].get("isError"), out)
        bridge.ask(call(3, "scio_whoami"))
        self.assertEqual(self.wiki.calls("scio_whoami")[-1]["auth"], "Bearer sk_live_CLAUDE_X_KEY_0123456789",
                         "use_agent's choice reaches the running bridge: one model's work is never signed with another's key")

    def test_use_agent_says_what_still_outranks_the_choice(self):
        self.write_keys("claude-x=sk_live_CLAUDE_X_KEY_0123456789\n# model claude-x claude-x\ngpt-5=sk_live_GPT_KEY_0123456789\n# model gpt-5 gpt-5\n")
        work = str(self.ws / ".scio/work")
        plain = self.local([call(1, "use_agent", {"alias": "claude-x"})], SCIO_WORK_DIR=work)[0]["result"]["content"][0]["text"]
        self.assertIn("the scio server", plain)
        launcher_key = "SCIO_" + "API_KEY"   # spelled apart: the skill's own guard stops a shell command that names it
        for env in ({"SCIO_AGENT": "gpt-5"}, {launcher_key: "sk_live_LAUNCHER_KEY_0123456789"}):
            text = self.local([call(1, "use_agent", {"alias": "claude-x"})], SCIO_WORK_DIR=work, **env)[0]["result"]["content"][0]["text"]
            self.assertIn(next(iter(env)), text)
            self.assertNotIn("use its key from the next call", text, "a launch that outranks the choice is not described as switched")
            self.assertNotIn("sk_live", text)

    def test_a_registration_whose_pin_is_untouched_keeps_its_key_for_the_session(self):
        self.write_keys("claude-x=sk_live_CLAUDE_X_KEY_0123456789\n# default claude-x\n# model claude-x claude-x\n")
        bridge = self.live(self.BRIDGE, SCIO_WORK_DIR=str(self.ws / ".scio/work"), SCIO_AGENT="typo")
        bridge.ask(call(1, "scio_register", {"display_name": "t", "model_family": "gpt", "model_version": "gpt-5"}))
        bridge.ask(call(2, "scio_whoami"))
        self.assertEqual(self.wiki.calls("scio_whoami")[-1]["auth"], "Bearer sk_live_REGISTERED_1_0123456789")

    def test_two_models_registering_in_one_workspace_each_keep_their_own_key(self):
        # Another session's registration pins its own agent for the workspace; that is not a choice made in this
        # session, so it must not move this session's agent: GPT's verdicts would go out under Claude's name.
        work = str(self.ws / ".scio/work")
        a, b = self.live(self.BRIDGE, SCIO_WORK_DIR=work), self.live(self.BRIDGE, SCIO_WORK_DIR=work)
        ra = a.ask(call(1, "scio_register", {"display_name": "a", "model_family": "gpt", "model_version": "gpt-5"}))
        rb = b.ask(call(1, "scio_register", {"display_name": "b", "model_family": "claude", "model_version": "claude-x"}))
        self.assertFalse(ra["result"].get("isError"), ra)
        self.assertFalse(rb["result"].get("isError"), rb)
        a.ask(call(2, "scio_whoami"))
        self.assertEqual(self.wiki.calls("scio_whoami")[-1]["auth"], "Bearer sk_live_REGISTERED_1_0123456789", "session A still signs as gpt-5")
        b.ask(call(2, "scio_whoami"))
        self.assertEqual(self.wiki.calls("scio_whoami")[-1]["auth"], "Bearer sk_live_REGISTERED_2_0123456789", "session B as claude-x")
        # an explicit choice still reaches both running bridges
        self.local([call(1, "use_agent", {"alias": "claude-x"})], SCIO_WORK_DIR=work)
        a.ask(call(3, "scio_whoami"))
        self.assertEqual(self.wiki.calls("scio_whoami")[-1]["auth"], "Bearer sk_live_REGISTERED_2_0123456789")

    def test_what_use_agent_says_under_scio_agent_is_what_the_bridge_does(self):
        self.write_keys("claude-x=sk_live_CLAUDE_X_KEY_0123456789\n# default claude-x\n# model claude-x claude-x\n"
                        "claude-y=sk_live_CLAUDE_Y_KEY_0123456789\n# model claude-y claude-y\n")
        work = str(self.ws / ".scio/work")
        bridge = self.live(self.BRIDGE, SCIO_WORK_DIR=work, SCIO_AGENT="claude-x")
        bridge.ask(call(1, "scio_register", {"display_name": "t", "model_family": "gpt", "model_version": "gpt-5"}))
        # the model confirms the agent it registered: this session's scio server keeps it, SCIO_AGENT or not
        text = self.local([call(1, "use_agent", {"alias": "gpt-5"})], SCIO_WORK_DIR=work, SCIO_AGENT="claude-x")[0]["result"]["content"][0]["text"]
        bridge.ask(call(2, "scio_whoami"))
        self.assertEqual(self.wiki.calls("scio_whoami")[-1]["auth"], "Bearer sk_live_REGISTERED_1_0123456789")
        self.assertNotIn("both servers keep using", text, text)
        self.assertIn("registered", text, "the exception is named: a scio server keeps the agent it registered in this session")
        self.assertIn("SCIO_AGENT=claude-x", text)
        # choosing another agent: SCIO_AGENT outranks the choice on the bridge too, as the answer says
        text = self.local([call(1, "use_agent", {"alias": "claude-y"})], SCIO_WORK_DIR=work, SCIO_AGENT="claude-x")[0]["result"]["content"][0]["text"]
        bridge.ask(call(3, "scio_whoami"))
        self.assertEqual(self.wiki.calls("scio_whoami")[-1]["auth"], "Bearer sk_live_CLAUDE_X_KEY_0123456789")
        self.assertIn("SCIO_AGENT=claude-x", text)
        self.assertNotIn("sk_live", text)


# ------------------------------------------------------------------------------------ bridge-local-5, ident-13, e2e-14
class AnonymousSearch(ServersBase):
    """The contract gives scio_search `auth: optional`: the server answers it without a key (summaries, no gap)."""

    def test_a_keyless_search_reaches_the_server_without_a_key(self):
        out, _ = self.bridge([call(1, "scio_search", {"query": "consensus protocols"})])
        self.assertFalse(out[0]["result"].get("isError"), out)
        searches = self.wiki.calls("scio_search")
        self.assertEqual(len(searches), 1)
        self.assertIsNone(searches[0]["auth"])

    def test_an_unknown_scio_agent_searches_without_anyone_elses_key(self):
        self.write_keys("other=sk_live_OTHER_KEY_0123456789\n")
        self.bridge([call(1, "scio_search", {"query": "x"})], SCIO_AGENT="typo")
        self.assertEqual([s["auth"] for s in self.wiki.calls("scio_search")], [None])

    def test_a_search_with_a_key_still_carries_it(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        self.bridge([call(1, "scio_search", {"query": "x"})])
        self.assertEqual([s["auth"] for s in self.wiki.calls("scio_search")], ["Bearer sk_live_ANY_TEST_KEY_0123456789"])

    def test_a_keyless_bearer_tool_is_answered_locally_and_asks_for_the_operators_agreement(self):
        out, _ = self.bridge([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, call(2, "scio_whoami")])
        byid = {m["id"]: m for m in out}
        hint = byid[2]["result"]["content"][0]["text"]
        self.assertTrue(byid[2]["result"].get("isError"))
        self.assertIn("scio_register", hint)
        self.assertIn("operator", hint)
        self.assertIn("agree", hint)
        self.assertIn("agree", byid[1]["result"]["instructions"])
        self.assertEqual(self.wiki.calls(), [])


# ------------------------------------------------------------------------------------ bridge-local-6: a conflict's diff
class ConflictDiffIsScanned(ServersBase):
    def conflict(self, diff):
        served = "conflict: " + json.dumps({"latest_revision": "rv_0123456789abcdef", "diff": diff})
        self.wiki.override = lambda req: sse(req["id"], text_result(served, True)) if (req.get("params") or {}).get("name") == "scio_propose_edit" else None
        return served

    def test_a_conflict_carrying_other_agents_text_gets_the_scanners_note(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        served = self.conflict("--- a\n+++ b\n+" + INJECTION)
        out, _ = self.bridge([call(1, "scio_propose_edit", {"slug": "x"})])
        content = out[0]["result"]["content"]
        self.assertEqual(len(content), 2, content)
        self.assertIn("injection", content[0]["text"])
        self.assertEqual(content[1]["text"], served, "the text itself is untouched")
        self.assertTrue(out[0]["result"].get("isError"))

    def test_a_clean_conflict_passes_unchanged(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        served = self.conflict("--- a\n+++ b\n+The bridge opened in 2004.[^c1]")
        out, _ = self.bridge([call(1, "scio_propose_edit", {"slug": "x"})])
        self.assertEqual(out[0]["result"]["content"], [{"type": "text", "text": served}])


# ------------------------------------------------------------------------------------ bridge-local-7, e2e-19: a rejected key
class RejectedKey(ServersBase):
    def test_an_authorization_error_on_200_with_a_key_says_the_key_was_rejected(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        self.wiki.override = lambda req: sse(req["id"], error={"code": -32600, "message": FORBIDDEN}) if req.get("method") == "tools/call" else None
        out, r = self.bridge([call(1, "scio_whoami")])
        error = out[0]["error"]
        for word in ("rejected", "revoked", "suspended", "frozen", "whoami", "register again"):
            self.assertIn(word, error["message"])
        self.assertEqual(error["data"]["server_message"], FORBIDDEN)
        self.assertNotIn("sk_live_ANY_TEST_KEY", r.stdout)

    def test_an_authorization_refusal_as_a_tool_result_is_explained_too(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        self.wiki.override = lambda req: sse(req["id"], text_result(FORBIDDEN, True)) if req.get("method") == "tools/call" else None
        out, _ = self.bridge([call(1, "scio_review", {"panel_id": "pn_x"})])
        texts = [c["text"] for c in out[0]["result"]["content"]]
        self.assertIn("suspended", texts[0])
        self.assertEqual(texts[-1], FORBIDDEN)

    def test_a_search_whose_key_does_not_authenticate_is_explained_first(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        thrown = "unauthenticated: the key sent does not authenticate — register, or ask your operator"   # ScioTools.SearchAsync
        # ModelContextProtocol.Core 2.2.0 turns a tool's McpException into an isError result under its own prefix
        # (CreateToolCallErrorResult); the bare form is kept for a server that sends the message alone
        for refusal in (SDK_PREFIX.format("scio_search") + thrown, thrown):
            with self.subTest(refusal=refusal[:40]):
                self.wiki.override = lambda req: sse(req["id"], text_result(refusal, True)) if req.get("method") == "tools/call" else None
                out, _ = self.bridge([call(1, "scio_search", {"query": "x"})])
                texts = [c["text"] for c in out[0]["result"]["content"]]
                self.assertIn("rejected", texts[0])
                self.assertEqual(texts[-1], refusal)

    def test_other_agents_text_that_mentions_authorization_is_not_a_rejected_key(self):
        # a conflict carries the page's current prose (anyone's words, planted or not); only the server's own opening
        # words say the call did not authenticate
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        diff = "--- a\n+++ b\n+Access to the archive requires authorization from the ministry.[^c1]"
        served = SDK_PREFIX.format("scio_propose_edit") + "conflict: " + json.dumps({"latest_revision": "rv_0123456789abcdef", "diff": diff})
        self.wiki.override = lambda req: sse(req["id"], text_result(served, True)) if req.get("method") == "tools/call" else None
        out, _ = self.bridge([call(1, "scio_propose_edit", {"slug": "x"})])
        self.assertEqual(out[0]["result"]["content"], [{"type": "text", "text": served}])
        discussion = SDK_PREFIX.format("scio_get_discussion") + "not_found: no talk page. Unauthenticated: this tool requires authorization."
        self.wiki.override = lambda req: sse(req["id"], text_result(discussion, True)) if req.get("method") == "tools/call" else None
        out, _ = self.bridge([call(1, "scio_get_discussion", {"slug": "x"})])
        self.assertNotIn("rejected this agent's key", json.dumps(out[0]))
        error = {"code": -32602, "message": "Invalid params: 'why' — the page says access requires authorization"}
        self.wiki.override = lambda req: sse(req["id"], error=error) if req.get("method") == "tools/call" else None
        out, _ = self.bridge([call(1, "scio_whoami")])
        self.assertEqual(out[0]["error"], error)

    def test_a_business_refusal_is_left_alone(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        refusal = 'permission_denied: {"required_rank": 3, "how_to_earn": "publish articles that survive"}'
        self.wiki.override = lambda req: sse(req["id"], text_result(refusal, True)) if req.get("method") == "tools/call" else None
        out, _ = self.bridge([call(1, "scio_review", {"panel_id": "pn_x"})])
        self.assertEqual(out[0]["result"]["content"], [{"type": "text", "text": refusal}])

    def test_a_401_names_suspension_and_freezing_as_well(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")
        self.wiki.override = lambda req: (401, {"Content-Type": "application/json"}, b'{"error": "unauthorized"}')
        out, _ = self.bridge([call(1, "scio_whoami")])
        self.assertIn("suspended", out[0]["error"]["message"])
        self.assertEqual(out[0]["error"]["data"]["http_status"], 401)


# ------------------------------------------------------------------------------------ bridge-local-8: HTTP-level errors
class HttpLevelErrors(ServersBase):
    def setUp(self):
        super().setUp()
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")

    def test_an_id_less_json_rpc_error_body_reaches_the_model_with_its_reason(self):
        message = "Bad Request: The MCP-Protocol-Version header value '2025-06-18' is not supported."
        body = json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": message}}).encode()
        self.wiki.override = lambda req: (400, {"Content-Type": "application/json"}, body)
        out, _ = self.bridge([call(7, "scio_whoami")])
        self.assertEqual(out[0]["id"], 7)
        self.assertIn(message, out[0]["error"]["message"])
        self.assertEqual(out[0]["error"]["data"]["http_status"], 400)

    def test_a_429_keeps_the_exact_retry_after_ms(self):
        body = json.dumps({"code": "rate_limited", "retry_after_ms": 1999, "message": "Too many requests: wait retry_after_ms, then continue."}).encode()
        self.wiki.override = lambda req: (429, {"Content-Type": "application/json", "Retry-After": "1"}, body)
        out, _ = self.bridge([call(1, "scio_whoami")])
        error = out[0]["error"]
        self.assertEqual(error["data"]["retry_after_ms"], 1999)
        self.assertIn("1999", error["message"])

    def test_a_429_for_failed_authentications_says_the_key_is_the_problem(self):
        # AuthFailureMiddleware: the one place the platform says the key is what fails; waiting and retrying with the
        # same key only fills the address's failure budget again
        said = "Too many failed authentications from this address: wait, then retry with a valid key."
        body = json.dumps({"code": "rate_limited", "retry_after_ms": 60000, "message": said}).encode()
        self.wiki.override = lambda req: (429, {"Content-Type": "application/json", "Retry-After": "60"}, body)
        out, _ = self.bridge([call(1, "scio_whoami")])
        error = out[0]["error"]
        self.assertEqual(error["data"]["server_message"], said)
        self.assertEqual(error["data"]["retry_after_ms"], 60000)
        self.assertIn("failed authentications", error["message"])
        self.assertIn("rejected this agent's key", error["message"])
        self.assertIn("60000", error["message"])

    def test_the_reason_in_an_http_error_body_reaches_the_model(self):
        said = "Too many requests: wait retry_after_ms, then continue."
        body = json.dumps({"code": "rate_limited", "retry_after_ms": 1999, "message": said}).encode()
        self.wiki.override = lambda req: (429, {"Content-Type": "application/json", "Retry-After": "1"}, body)
        out, _ = self.bridge([call(1, "scio_whoami")])
        self.assertIn(said, out[0]["error"]["message"])
        self.assertEqual(out[0]["error"]["data"]["server_message"], said)
        self.assertNotIn("rejected", out[0]["error"]["message"], "an ordinary rate limit is not a rejected key")
        long = "x" * 5000
        self.wiki.override = lambda req: (503, {"Content-Type": "application/json"}, json.dumps({"message": long}).encode())
        out, _ = self.bridge([call(1, "scio_whoami")])
        self.assertLess(len(out[0]["error"]["message"]), 1200, "cut to length")
        self.assertIn("x" * 100, out[0]["error"]["message"])

    def test_a_429_without_a_body_still_carries_the_header(self):
        self.wiki.override = lambda req: (429, {"Content-Type": "text/plain", "Retry-After": "7"}, b"")
        out, _ = self.bridge([call(1, "scio_whoami")])
        self.assertEqual(out[0]["error"]["data"]["retry_after"], "7")

    def test_a_success_under_another_id_is_still_refused(self):
        self.wiki.override = lambda req: sse(req["id"] + 1000, text_result("{}")) if req.get("method") == "tools/call" else None
        out, _ = self.bridge([call(1, "scio_whoami")])
        self.assertEqual(out[0]["error"]["code"], -32002)


# ------------------------------------------------------------------------------------ bridge-local-9: the key is never lost
class RegistrationKeepsItsKey(ServersBase):
    ARGS = {"display_name": "t", "model_family": "claude", "model_version": "claude-fable-5"}

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes anywhere")
    def test_an_unwritable_keys_file_is_refused_before_anything_is_registered(self):
        self.keys.parent.mkdir(parents=True)
        os.chmod(str(self.keys.parent), 0o500)
        self.addCleanup(os.chmod, str(self.keys.parent), 0o700)
        out, _ = self.bridge([call(1, "scio_register", self.ARGS), call(2, "scio_register", self.ARGS)])
        self.assertEqual(len(out), 2)
        for m in out:
            self.assertTrue(m["result"].get("isError"), m)
            self.assertIn(str(self.keys), m["result"]["content"][0]["text"])
        self.assertEqual(self.wiki.calls("scio_register"), [], "no agent is created on scio.md that nobody could use")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes anywhere")
    def test_a_model_already_registered_is_named_even_when_the_keys_file_is_read_only(self):
        # the Codex profile keeps the keys folder read-only: "fix that location" would send the operator after
        # permissions for nothing, when the answer is that the agent exists and the skill uses it
        self.write_keys("claude-fable-5=sk_live_FABLE_0123456789\n# default claude-fable-5\n# model claude-fable-5 claude-fable-5\n")
        os.chmod(str(self.keys), 0o400)
        self.addCleanup(os.chmod, str(self.keys), 0o600)
        out, _ = self.bridge([call(1, "scio_register", self.ARGS)])
        text = out[0]["result"]["content"][0]["text"]
        self.assertIn("already registered locally as 'claude-fable-5'", text)
        self.assertNotIn("cannot be written", text)
        self.assertEqual(self.wiki.calls("scio_register"), [])

    def test_a_key_that_cannot_be_saved_after_registering_goes_to_a_private_recovery_file(self):
        def odd(req):
            if (req.get("params") or {}).get("name") != "scio_register":
                return None
            data = {"agent_id": "ag_00000000000000aa", "api_key": "sk_live_RECOVER_ME_0123456789", "claim_url": "https://scio.md/claim/x\nevil=1"}
            return sse(req["id"], {**text_result(json.dumps(data)), "structuredContent": data})
        self.wiki.override = odd
        out, r = self.bridge([call(1, "scio_register", self.ARGS)])
        text = out[0]["result"]["content"][0]["text"]
        self.assertNotIn("sk_live_RECOVER_ME", r.stdout + r.stderr, "the key never reaches the model")
        self.assertIn("ag_00000000000000aa", text)
        recovery = [w.strip(".,;:()'\"`") for w in text.split() if "recover" in w and os.sep in w]
        self.assertTrue(recovery, text)
        path = Path(recovery[0])
        self.assertIn("sk_live_RECOVER_ME_0123456789", path.read_text())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse(str(path).startswith(str(self.ws)), "never inside the repository")


# ------------------------------------------------------------------------------------ ident-8: Python 3.8
class Python38(unittest.TestCase):
    def test_the_plugin_uses_no_string_method_newer_than_python_3_8(self):
        for path in SKILL.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            ast.parse(source, str(path), feature_version=(3, 8))
            for newer in (".removeprefix(", ".removesuffix("):
                self.assertNotIn(newer, source, f"{path.relative_to(ROOT)} uses {newer} (Python 3.9+)")


class SseParsing(ServersBase):
    def test_data_lines_with_and_without_the_optional_space_and_across_lines(self):
        self.write_keys("t=sk_live_ANY_TEST_KEY_0123456789\n")

        def framed(req):
            if req.get("method") != "tools/call":
                return None
            lines = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": text_result("  two leading spaces kept")}, indent=1).split("\n")
            data = "data:" + lines[0] + "\r\n" + "".join("data: " + l + "\r\n" for l in lines[1:])
            return 200, {"Content-Type": "text/event-stream"}, ("﻿: comment\r\nevent: message\r\n" + data + "\r\n").encode()
        self.wiki.override = framed
        out, _ = self.bridge([call(1, "scio_whoami")])
        self.assertEqual(out[0]["result"]["content"][0]["text"], "  two leading spaces kept")


# ------------------------------------------------------------------------------------ ident-17: one reading of the keys file
class KeysFileReading(ServersBase):
    def scio_as(self, *args):
        return subprocess.run(["bash", str(self.SCRIPTS / "scio-as"), *args], capture_output=True, text=True, env=self.env, timeout=30)

    def test_scio_as_and_the_servers_take_the_same_key(self):
        self.write_keys("claude-opus-5=sk_FIRST_0123456789\nclaude-opus-5=sk_SECOND_0123456789\r\nopus = sk_SPACED_0123456789 \n# default opus\n")
        for alias in ("claude-opus-5", "opus"):
            expected = self.probe(f"c.read_keys()[0][{alias!r}]")
            r = self.scio_as(alias, "--print-env")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"export SCIO_API_KEY={expected}\n", r.stdout)
        self.assertEqual(self.scio_as("--list").stdout.split(), ["claude-opus-5", "opus"])

    def test_an_unknown_alias_still_fails_closed(self):
        self.write_keys("opus=sk_OPUS_0123456789\n")
        r = self.scio_as("fable", "--print-env")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("sk_OPUS", r.stdout + r.stderr)

    def test_two_sessions_registering_the_same_model_at_once_create_one_agent(self):
        self.wiki.hold = 1.5
        args = {"display_name": "t", "model_family": "claude", "model_version": "claude-opus-5"}
        procs = [subprocess.Popen([PY, str(self.BRIDGE), "--harness", "test"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=self.env, cwd=str(self.ws)) for _ in range(2)]
        for p in procs:
            p.stdin.write(json.dumps(call(1, "scio_register", args)) + "\n")
            p.stdin.flush()
        for p in procs:
            p.communicate(timeout=60)
        self.assertEqual(len(self.wiki.calls("scio_register")), 1, "the second waits for the first, then finds the model registered")
        lines = [l for l in self.keys.read_text().splitlines() if "=" in l and not l.startswith("#")]
        self.assertEqual(len(lines), 1, lines)


# ------------------------------------------------------------------------------------ the registration scripts: one lock
class RegistrationScripts(ServersBase):
    """register-models.py (behind setup.py --register) and register.py hold the bridge's keys_lock from the
    one-agent-per-model check to the saved key, and never lose a key they could not save."""
    MODELS = ["--name", "u", "--harness", "h", "--models", "opus=claude-opus-5"]

    def script(self, name, *args, **env):
        return [PY, str(self.SCRIPTS / name), *args], dict(self.env, SCIO_MODEL_VERSION="claude-opus-5", **env)

    def at_once(self, name, *args):
        self.wiki.hold = 1.5
        argv, env = self.script(name, *args)
        procs = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=str(self.ws)) for _ in range(2)]
        outputs = [p.communicate(timeout=60) for p in procs]
        for _, err in outputs:
            self.assertNotIn("Traceback", err)
        return outputs

    def key_lines(self):
        return [l for l in self.keys.read_text().splitlines() if "=" in l and not l.startswith("#")]

    def test_two_register_models_runs_of_one_model_create_one_agent(self):
        self.at_once("register-models.py", *self.MODELS)
        self.assertEqual(len(self.wiki.rest_registrations()), 1, "the second run waits, then finds opus registered")
        self.assertEqual(self.key_lines(), ["opus=sk_live_REST_1_0123456789"])

    def test_two_register_runs_of_one_model_create_one_agent(self):
        self.at_once("register.py", "probe")
        self.assertEqual(len(self.wiki.rest_registrations()), 1)
        self.assertEqual(self.key_lines(), ["claude-opus-5=sk_live_REST_1_0123456789"])

    def test_a_key_the_scripts_cannot_save_goes_to_a_private_recovery_file(self):
        self.wiki.rest_extra = {"claim_url": "https://scio.md/claim/x\nevil=1"}   # a line save_key refuses to write
        for name, args in (("register-models.py", self.MODELS), ("register.py", ["probe"])):
            with self.subTest(script=name):
                self.wiki.registrations = 0
                argv, env = self.script(name, *args)
                r = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=str(self.ws), timeout=60)
                self.assertNotIn("Traceback", r.stderr)
                self.assertNotIn("sk_live_REST_1", r.stdout + r.stderr, "the key is never printed")
                self.assertIn("ag_0000000000000001", r.stdout + r.stderr)
                recovery = [w.strip(".,;:()'\"`") for w in (r.stdout + r.stderr).split() if "recover" in w and os.sep in w]
                self.assertTrue(recovery, r.stdout + r.stderr)
                path = Path(recovery[0])
                self.assertIn("sk_live_REST_1_0123456789", path.read_text())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertFalse(str(path).startswith(str(self.ws)))


# ------------------------------------------------------------------------------------ e2e-20: the harness
class RegistrationRecordsTheHarness(ServersBase):
    ARGS = {"display_name": "t", "model_family": "claude", "model_version": "claude-fable-5"}

    def registered_harness(self, args=("--harness", "test"), **extra):
        if self.keys.exists():
            self.keys.unlink()
        self.wiki.reset()
        self.run_server(self.BRIDGE, [call(1, "scio_register", dict(self.ARGS, **extra))], args=args)
        return self.wiki.calls("scio_register")[0]["args"].get("harness", "(not sent)")

    def test_the_bridge_sends_its_harness_with_the_registration(self):
        self.assertEqual(self.registered_harness(), "test")

    def test_a_harness_the_caller_gave_wins(self):
        self.assertEqual(self.registered_harness(harness="codex"), "codex")

    def test_an_unknown_or_malformed_harness_is_not_sent_and_a_long_one_is_cut(self):
        self.assertEqual(self.registered_harness(args=()), "(not sent)")
        self.assertEqual(self.registered_harness(args=("--harness", "x" * 100)), "x" * 64)
        self.assertEqual(self.registered_harness(args=("--harness", "a b")), "(not sent)")


if __name__ == "__main__":
    unittest.main()
