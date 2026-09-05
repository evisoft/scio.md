#!/usr/bin/env python3
"""Security and reliability regressions using disposable files and remote doubles."""
import importlib.util
import http.server
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/scio/scripts"
sys.path.insert(0, str(SCRIPTS))
import scio_common


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


bridge = load_module("hardening_bridge", ROOT / "skills/scio/server/scio_bridge.py")


class HardeningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="scio-hardening-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.work = self.base / "work"
        self.work.mkdir()
        self.env = dict(os.environ, SCIO_WORK_DIR=str(self.work), SCIO_KEYS_FILE=str(self.base / "keys"),
                        SCIO_API_KEY="", SCIO_AGENT="", SCIO_AUTO_APPROVE="1")
        env_patch = patch.dict(os.environ, self.env)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def run_script(self, script, args=(), payload=None, **env):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                              input=json.dumps(payload) if payload is not None else None,
                              capture_output=True, text=True, cwd=self.base,
                              env=dict(self.env, **env), timeout=15)

    def test_workdir_rejects_task_symlink_before_creating_external_files(self):
        created = self.run_script("workdir.py", ["write", "example"])
        self.assertEqual(created.returncode, 0, created.stderr)
        task = Path(created.stdout.strip())
        task.rename(self.work / "old-task")
        outside = self.base / "outside"
        outside.mkdir()
        task.symlink_to(outside, target_is_directory=True)
        result = self.run_script("workdir.py", ["write", "example"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_prune_preserves_unrelated_folders_with_task_json(self):
        other = self.work / "customer-project"
        other.mkdir()
        (other / "task.json").write_text('{"title":"unrelated work"}')
        (other / "notes.txt").write_text("must survive")
        result = self.run_script("workdir.py", ["--prune", "0"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((other / "notes.txt").exists())

    def test_secret_guard_denies_basename_spaces_and_symlink_paths(self):
        credentials = self.base / "private credentials"
        credentials.write_text("demo=TEST_CREDENTIAL_1234567890\n")
        link = self.base / "shortcut"
        link.symlink_to(credentials)
        for path in (credentials.name, str(credentials), str(link)):
            with self.subTest(path=path):
                result = self.run_script("guard-secrets.py", payload={"tool_name": "Read", "tool_input": {"file_path": path}},
                                         SCIO_KEYS_FILE=str(credentials))
                self.assertIn('"deny"', result.stdout, result.stderr)

    def test_secret_guard_survives_invalid_utf8_in_credential_file(self):
        credentials = self.base / "keys"
        credentials.write_bytes(b"# invalid comment \xff\ndemo=TEST_CREDENTIAL_1234567890\n")
        result = self.run_script("guard-secrets.py", payload={"tool_name": "WebFetch", "tool_input": {
            "url": "https://example.org/?value=TEST_CREDENTIAL_1234567890"}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"deny"', result.stdout)

    def test_secret_guard_denies_relative_shell_reads_and_keys_variable(self):
        credentials = self.base / "private credentials"
        credentials.write_text("demo=TEST_CREDENTIAL_1234567890\n")
        for command in ("cat 'private credentials'", 'cat "$SCIO_KEYS_FILE"'):
            with self.subTest(command=command):
                result = self.run_script("guard-secrets.py", payload={"tool_name": "Bash", "tool_input": {"command": command}},
                                         SCIO_KEYS_FILE=str(credentials))
                self.assertIn('"deny"', result.stdout, result.stderr)

    def test_key_metadata_rejects_every_record_separator(self):
        for separator in ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            with self.subTest(separator=repr(separator)), self.assertRaises(ValueError):
                scio_common.save_key("demo", "TEST_CREDENTIAL_1234567890", "model" + separator + "other=injected")
        self.assertFalse((self.base / "keys").exists())

    def test_registration_rejects_unpersistable_model_before_remote_call(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "scio_register", "arguments": {"alias": "demo", "model_version": "model\u2028other=value"}}}
        with patch.object(bridge, "forward", return_value={"result": {}}) as remote, patch.object(bridge, "reply"):
            bridge.register(request)
        remote.assert_not_called()

    def test_preflight_rejects_invalid_claim_types_without_tracebacks(self):
        clean = json.loads((ROOT / "tests/redteam/clean.proposal.json").read_text())
        cases = json.loads((ROOT / "tests/redteam/14-invalid-claim-types.json").read_text())
        for case in cases:
            field, value = case["field"], case["value"]
            with self.subTest(field=field):
                proposal = json.loads(json.dumps(clean))
                proposal["claims"][0][field] = value
                path = self.work / "proposal.json"
                path.write_text(json.dumps(proposal))
                result = self.run_script("check-claims.py", [path])
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("ERROR", result.stdout)
                self.assertNotIn("Traceback", result.stderr)

    def test_preflight_rejects_nonobject_hook_payload(self):
        result = self.run_script("check-claims.py", payload=[])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"deny"', result.stdout)

    def response(self, data, content_type):
        response = io.BytesIO(data.encode())
        response.headers = {"Content-Type": content_type}
        return response

    def test_bridge_reads_multiline_sse_event(self):
        for newline in ("\n", "\r\n", "\r"):
            data = newline.join(['\ufeffdata: {"jsonrpc":"2.0",', 'data: "id":7,"result":{"ok":true}}', '', ''])
            with self.subTest(newline=repr(newline)), patch.object(bridge.OPENER, "open", return_value=self.response(data, "text/event-stream")):
                answer = bridge.forward({"jsonrpc": "2.0", "id": 7, "method": "ping"})
            self.assertEqual(answer.get("result"), {"ok": True})

    def test_bridge_returns_response_before_event_stream_closes(self):
        release = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'data: {"jsonrpc":"2.0","id":7,"result":{"ok":true}}\n\n')
                self.wfile.flush()
                release.wait(3)
                self.close_connection = True

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            start = time.monotonic()
            with patch.object(bridge, "REMOTE", f"http://127.0.0.1:{server.server_port}/mcp"):
                answer = bridge.forward({"jsonrpc": "2.0", "id": 7, "method": "ping"})
            self.assertEqual(answer.get("result"), {"ok": True})
            self.assertLess(time.monotonic() - start, 2)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_bridge_does_not_turn_unmatched_or_missing_response_into_success(self):
        cases = (
            ('data: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n', "text/event-stream"),
            ('data: {"jsonrpc":"2.0","id":8,"result":{"wrong":true}}\n\n', "text/event-stream"),
            ('{"jsonrpc":"2.0","id":8,"result":{"wrong":true}}', "application/json"),
            ('{}', "application/json"),
            ('', "application/json"),
        )
        for data, content_type in cases:
            with self.subTest(data=data), patch.object(bridge.OPENER, "open", return_value=self.response(data, content_type)):
                answer = bridge.forward({"jsonrpc": "2.0", "id": 7, "method": "ping"})
                self.assertIn("error", answer)

    def test_release_stops_before_tagging_when_commit_fails(self):
        checkout = self.base / "checkout"
        shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", ".scio", ".remember", "__pycache__"))
        binaries = self.base / "bin"
        binaries.mkdir()
        log = self.base / "release-commands"
        commands = {
            "git": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$RELEASE_TEST_LOG"\n'
                   'case "$1" in commit) exit 1;; diff) exit 1;; esac\n',
            "gh": '#!/bin/sh\nprintf "gh %s\\n" "$*" >> "$RELEASE_TEST_LOG"\n',
            "python3": '#!/bin/sh\ncase "$1" in scripts/gen-manifest.py) exec "$RELEASE_TEST_PYTHON" "$@";; esac\n',
            "claude": '#!/bin/sh\nexit 0\n',
        }
        for name, text in commands.items():
            path = binaries / name
            path.write_text(text)
            path.chmod(0o755)
        result = subprocess.run(["bash", str(checkout / "scripts/release.sh"), "0.6.2"], capture_output=True, text=True,
                                env=dict(self.env, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                                         RELEASE_TEST_LOG=str(log), RELEASE_TEST_PYTHON=sys.executable), timeout=15)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        seen = log.read_text().splitlines()
        self.assertTrue(any(line.startswith("commit ") for line in seen), seen)
        self.assertFalse(any(line.startswith(("tag ", "push ", "gh release ")) for line in seen), seen)


if __name__ == "__main__":
    unittest.main()
