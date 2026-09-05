#!/usr/bin/env python3
"""Behavior regressions from the September 2026 code review; no live API calls."""
import base64
import fnmatch
import importlib.util
import io
import json
import os
import re
import runpy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/scio/scripts"
SERVER = ROOT / "skills/scio/server"
sys.path.insert(0, str(SCRIPTS))
import scio_common


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


local = module("review_local", SERVER / "scio_local.py")
bridge = module("review_bridge", SERVER / "scio_bridge.py")


def decision(rules, value):
    # OpenCode's documented contract: the LAST matching rule wins.
    return next((action for pattern, action in reversed(list(rules.items()))
                 if isinstance(action, str) and fnmatch.fnmatchcase(value, pattern)), None)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="scio-review-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.work = self.base / "work"
        self.task = self.work / "task"
        self.task.mkdir(parents=True)
        self.env = dict(os.environ, SCIO_WORK_DIR=str(self.work), SCIO_KEYS_FILE=str(self.base / "keys"),
                        SCIO_API_KEY="", SCIO_AGENT="", SCIO_AUTO_APPROVE="1", CLAUDE_PLUGIN_ROOT=str(ROOT))
        self.env_patch = patch.dict(os.environ, self.env)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def run_script(self, script, args=(), payload=None, env=None):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                              input=json.dumps(payload) if payload is not None else None,
                              capture_output=True, text=True, env=env or self.env, cwd=self.base, timeout=15)

    def draft(self):
        proposal = json.loads((ROOT / "tests/redteam/clean.proposal.json").read_text())
        (self.task / "claims.json").write_text(json.dumps(proposal["claims"]), encoding="utf-8")
        (self.task / "draft.md").write_text(proposal["body"], encoding="utf-8")

    def test_build_rejects_symlinked_inputs_without_echoing_external_data(self):
        self.draft()
        external = self.base / "private.md"
        external.write_text("---\nsummary: private\n---\nPRIVATE_OUTSIDE_CONTENT")
        (self.task / "draft.md").unlink()
        (self.task / "draft.md").symlink_to(external)
        try:
            answer = local.t_build_proposal({"dir": str(self.task), "slug": "review", "lang": "en"})
        except ValueError:
            answer = "refused"
        self.assertNotIn("PRIVATE_OUTSIDE_CONTENT", answer)
        self.assertFalse((self.task / "proposal.json").exists())

    def test_cli_build_rejects_output_symlink_without_overwriting_target(self):
        self.draft()
        external = self.base / "private.json"
        external.write_text("keep me")
        (self.task / "proposal.json").symlink_to(external)
        r = self.run_script("build-proposal.py", [self.task, "--slug", "review", "--lang", "en"])
        self.assertEqual(external.read_text(), "keep me")
        self.assertNotEqual(r.returncode, 0)

    def test_autoapprove_does_not_approve_scan_traversal_or_symlink(self):
        external = self.base / "private.txt"
        external.write_text("private")
        (self.task / "link").symlink_to(external)
        for path in (self.task / "../../private.txt", self.task / "link"):
            with self.subTest(path=path):
                r = self.run_script("auto-approve.py", payload={"tool_name": "Bash", "tool_input": {
                    "command": f"python3 {SCRIPTS}/scan-injection.py {path}"}})
                self.assertNotIn('"allow"', r.stdout)

    def test_vscode_scanner_approval_does_not_accept_escaped_paths(self):
        cfg = json.loads((ROOT / "vscode/settings.scio.json").read_text())
        patterns = [p[1:-1].replace("__SCIO_SCRIPTS__", re.escape(str(SCRIPTS)))
                    for p, allow in cfg["chat.tools.terminal.autoApprove"].items() if allow]
        cmd = f"python3 {SCRIPTS}/scan-injection.py /tmp/.scio/work/../../private.txt"
        self.assertFalse(any(re.search(p, cmd) for p in patterns))

    def test_malformed_tool_names_do_not_terminate_local_server(self):
        requests = [{"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name}}
                    for n, name in enumerate(([], {}, 42), 1)]
        requests.append({"jsonrpc": "2.0", "id": 4, "method": "ping"})
        r = subprocess.run([sys.executable, str(SERVER / "scio_local.py")],
                           input="".join(json.dumps(req) + "\n" for req in requests),
                           capture_output=True, text=True, env=self.env, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        answers = {a["id"]: a for a in map(json.loads, r.stdout.splitlines())}
        self.assertEqual(answers[4]["result"], {})
        for n in (1, 2, 3):
            self.assertEqual(answers[n]["error"]["code"], -32602)

    def test_seconds_wait_returns_reusable_deadline(self):
        with patch.object(local.time, "time", side_effect=[1000, 1050]), patch.object(local.time, "sleep"):
            first = json.loads(local.t_wait({"seconds": 120}))
        self.assertIn("until", first)
        with patch.object(local.time, "time", side_effect=[1050, 1100]), patch.object(local.time, "sleep"):
            second = json.loads(local.t_wait({"until": first["until"]}))
        self.assertEqual(second["remaining_seconds"], 20)

    def test_proposal_file_array_is_denied_by_hook(self):
        path = self.task / "proposal.json"
        path.write_text((ROOT / "tests/redteam/13-nonobject-proposal.json").read_text())
        r = self.run_script("check-claims.py", payload={"tool_input": {"proposal_file": str(path)}})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_guard_adapters_deny_when_child_guard_crashes(self):
        runtime = self.base / "runtime"
        shutil.copytree(SCRIPTS, runtime, ignore=shutil.ignore_patterns("__pycache__"))
        (runtime / "guard-secrets.py").write_text("raise RuntimeError('test guard failure')\n")
        for script, payload, field in (
            ("cursor-hook.py", {"tool_name": "scio_whoami", "mcp_server_name": "scio", "tool_input": {}}, "permission"),
            ("agy-hook.py", {"toolCall": {"name": "scio/scio_whoami", "args": {}}}, "decision"),
        ):
            with self.subTest(script=script):
                r = subprocess.run([sys.executable, str(runtime / script)], input=json.dumps(payload),
                                   capture_output=True, text=True, env=self.env, timeout=10)
                self.assertEqual(json.loads(r.stdout).get(field), "deny")

    def test_bridge_reports_scanner_crash(self):
        failed = subprocess.CompletedProcess([], 2, "", "scanner failed")
        with patch.object(bridge.subprocess, "run", return_value=failed):
            _, error = bridge.scan_findings("ordinary text")
        self.assertIsNotNone(error)

    def test_bridge_reports_unscanned_tail(self):
        result = {"content": [{"type": "text", "text": "a " * 200001}]}
        with patch.object(bridge, "scan_findings", return_value=("", None)):
            wrapped = bridge.with_scan_envelope("scio_get_article", result)
        self.assertGreater(len(wrapped["content"]), 1)
        self.assertEqual(wrapped["content"][-1], result["content"][0])

    def test_save_key_supports_relative_paths(self):
        r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                            "from scio_common import save_key; save_key('demo', 'test_key', 'model')", str(SCRIPTS)],
                           cwd=self.base, env=dict(self.env, SCIO_KEYS_FILE="relative-keys"), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_save_key_rejects_line_injection(self):
        with self.assertRaises(ValueError):
            scio_common.save_key("demo", "test_key", "model\nother=injected_key")
        self.assertFalse((self.base / "keys").exists())

    def test_batch_registration_preserves_unterminated_existing_key(self):
        path = self.base / "keys"
        path.write_text("old=old_key")
        response = {"api_key": "new_key", "agent_id": "ag_test", "claim_url": "https://scio.md/claim/test"}
        with patch.object(scio_common.OPENER, "open", return_value=io.BytesIO(json.dumps(response).encode())), \
             patch.object(sys, "argv", ["register-models.py", "--name", "test", "--models", "new=new-model"]), \
             patch("sys.stdout", new_callable=io.StringIO), self.assertRaises(SystemExit) as ended:
            runpy.run_path(str(SCRIPTS / "register-models.py"), run_name="__main__")
        self.assertEqual(ended.exception.code, 0)
        self.assertEqual(scio_common.read_keys()[0], {"old": "old_key", "new": "new_key"})

    def test_codex_servers_share_custom_work_root(self):
        # Setup writes only into this temporary home.
        r = self.run_script("setup.py", ["--harness", "codex", "--yes"], env=dict(self.env, HOME=str(self.base)))
        self.assertEqual(r.returncode, 0, r.stderr)
        for path in (self.base / ".codex/config.toml", ROOT / "codex/config.scio.toml"):
            cfg = tomllib.loads(path.read_text())
            for name in ("scio", "scio-local"):
                self.assertIn("SCIO_WORK_DIR", cfg["mcp_servers"][name]["env_vars"], str(path))

    def test_opencode_effective_permissions_preserve_sensitive_prompts(self):
        path = self.base / ".config/opencode/opencode.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"permission": {"bash": {"*": "allow", "git *": "deny"}}}))
        for _ in range(2):
            r = self.run_script("setup.py", ["--harness", "opencode", "--trust", "--yes"], env=dict(self.env, HOME=str(self.base)))
            self.assertEqual(r.returncode, 0, r.stderr)
            cfg = json.loads(path.read_text())["permission"]
            for tool in ("scio_scio_register", "scio_scio_contest", "scio_scio_suspend"):
                self.assertEqual(decision(cfg, tool), "ask", tool)
            self.assertEqual(decision(cfg, "scio_scio_whoami"), "allow")
            self.assertEqual(decision(cfg["bash"], "git push"), "deny")
            self.assertEqual(decision(cfg["bash"], "echo hello"), "allow")
            self.assertEqual(decision(cfg["bash"], f"{SCRIPTS}/scio-as demo bash"), "ask")
            self.assertEqual(decision(cfg["bash"], f"python3 {SCRIPTS}/workdir.py --prune 0"), "ask")
            self.assertEqual(decision(cfg["bash"], f"python3 {SCRIPTS}/workdir.py write demo"), "allow")

    def test_rules_check_verifies_signature_and_actual_bundled_text(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        runtime = self.base / "scio"
        shutil.copytree(SCRIPTS.parent, runtime, ignore=shutil.ignore_patterns("__pycache__"))
        key = Ed25519PrivateKey.generate()
        pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        skill = runtime / "SKILL.md"
        skill.write_text(re.sub(r'rules-signing-key: "ed25519:[^"]+"', f'rules-signing-key: "ed25519:{pub}"', skill.read_text()))
        rules = {"version": "2026-09-05", "constitution_markdown": "# Constitution\n\nVerified fixture text.\n"}
        canonical = json.dumps(rules)
        served = {"version": rules["version"], "canonical": canonical, "rules": rules,
                  "signature": base64.b64encode(key.sign(canonical.encode())).decode(), "signing_key_id": "fixture"}

        def refresh(doc, check=False):
            with patch.object(scio_common.OPENER, "open", return_value=io.BytesIO(json.dumps(doc).encode())), \
                 patch.object(sys, "argv", ["refresh-rules.py"] + (["--check"] if check else [])), \
                 patch("sys.stdout", new_callable=io.StringIO):
                try:
                    runpy.run_path(str(runtime / "scripts/refresh-rules.py"), run_name="__main__")
                except SystemExit as e:
                    return e.code or 0
            return 0

        self.assertEqual(refresh(served), 0)
        self.assertEqual(refresh(served, check=True), 0)
        bad = dict(served, signature=base64.b64encode(b"\0" * 64).decode())
        with self.subTest(case="invalid signature"):
            self.assertNotEqual(refresh(bad, check=True), 0)
        bundled = runtime / "references/rules.md"
        bundled.write_text(bundled.read_text() + "Tampered local content.\n")
        with self.subTest(case="modified bundled text"):
            self.assertNotEqual(refresh(served, check=True), 0)


if __name__ == "__main__":
    unittest.main()
