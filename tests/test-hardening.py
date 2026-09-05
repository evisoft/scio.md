#!/usr/bin/env python3
"""Security and reliability regressions using disposable files and remote doubles."""
import importlib.util
import http.server
import io
import json
import os
import runpy
import shutil
import socket
from contextlib import redirect_stdout
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

    def test_prune_removes_owned_tasks_and_skips_malformed_metadata(self):
        created = self.run_script("workdir.py", ["write", "example"])
        self.assertEqual(created.returncode, 0, created.stderr)
        task = Path(created.stdout.strip())
        other = self.work / "unrelated"
        other.mkdir()
        (other / "task.json").write_text('{"kind":[],"ref":"example","agent":"anon"}')
        listed = self.run_script("workdir.py", ["--list"])
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(task.name, listed.stdout)
        self.assertNotIn(other.name, listed.stdout)
        pruned = self.run_script("workdir.py", ["--prune", "0"])
        self.assertEqual(pruned.returncode, 0, pruned.stderr)
        self.assertFalse(task.exists())
        self.assertTrue(other.exists())

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

    def test_secret_guard_recognizes_paths_next_to_shell_operators(self):
        credentials = self.base / "private credentials"
        credentials.write_text("demo=TEST_CREDENTIAL_1234567890\n")
        cases = json.loads((ROOT / "tests/redteam/15-shell-credential-paths.json").read_text())
        for command in cases:
            with self.subTest(command=command):
                result = self.run_script("guard-secrets.py", payload={"tool_name": "Bash", "tool_input": {"command": command}},
                                         SCIO_KEYS_FILE=str(credentials))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('"deny"', result.stdout, result.stderr)

    def test_secret_guard_allows_unrelated_compound_shell_commands(self):
        for command in ("cat 'public notes';true", "cat<'public notes'", "cat 'public notes'|wc -c"):
            with self.subTest(command=command):
                result = self.run_script("guard-secrets.py", payload={"tool_name": "Bash", "tool_input": {"command": command}})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_key_metadata_rejects_every_record_separator(self):
        for separator in ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            with self.subTest(separator=repr(separator)), self.assertRaises(ValueError):
                scio_common.save_key("demo", "TEST_CREDENTIAL_1234567890", "model" + separator + "other=injected")
        self.assertFalse((self.base / "keys").exists())

    def test_trust_grant_and_revoke_support_relative_file(self):
        env = {"SCIO_TRUST_FILE": "local-trust", "SCIO_AUTO_APPROVE": ""}
        granted = self.run_script("trust.py", ["--grant"], **env)
        self.assertEqual(granted.returncode, 0, granted.stderr)
        self.assertEqual((self.base / "local-trust").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.run_script("trust.py", ["--status"], **env).returncode, 0)
        self.assertEqual(self.run_script("trust.py", ["--revoke"], **env).returncode, 0)
        self.assertFalse((self.base / "local-trust").exists())
        self.assertEqual(self.run_script("trust.py", ["--status"], **env).returncode, 1)

    def test_launcher_crlf_key_is_normalized_for_requests(self):
        (self.base / "keys").write_bytes(b"demo=TEST_CREDENTIAL_1234567890\r\n")
        check = ("import sys; sys.path.insert(0, sys.argv[1]); from scio_common import env_key; "
                 "sys.exit(0 if env_key() == 'TEST_CREDENTIAL_1234567890' else 1)")
        result = subprocess.run(["bash", str(SCRIPTS / "scio-as"), "demo", sys.executable, "-c", check, str(SCRIPTS)],
                                capture_output=True, text=True, env=self.env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_bridge_does_not_echo_malformed_bearer_in_transport_errors(self):
        secret = "TEST_CREDENTIAL_1234567890"
        for suffix in ("\r", "\n", "\r\n", "\rbroken", "\u03bb"):
            with self.subTest(suffix=repr(suffix)), patch.dict(os.environ, SCIO_API_KEY=secret + suffix), \
                    patch.object(bridge, "REMOTE", "http://127.0.0.1:1/mcp"), \
                    patch.object(socket, "create_connection", side_effect=OSError("network disabled for test")):
                answer = bridge.forward({"jsonrpc": "2.0", "id": 7, "method": "ping"})
                self.assertIn("error", answer)
                self.assertNotIn(secret, json.dumps(answer))

    def test_whoami_does_not_echo_malformed_bearer_in_transport_errors(self):
        secret = "TEST_CREDENTIAL_1234567890"
        for suffix in ("\r", "\rbroken"):
            output = io.StringIO()
            with self.subTest(suffix=repr(suffix)), patch.dict(os.environ, SCIO_API_KEY=secret + suffix), \
                    patch.object(scio_common, "API", "http://127.0.0.1:1/v1"), \
                    patch.object(socket, "create_connection", side_effect=OSError("network disabled for test")), \
                    redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(SCRIPTS / "whoami.py"), run_name="__main__")
            self.assertEqual(stopped.exception.code, 0)
            self.assertIn("could not reach", output.getvalue())
            self.assertNotIn(secret, output.getvalue())

    def test_show_claims_does_not_echo_credentials_from_transport_exception(self):
        secret = "TEST_CREDENTIAL_1234567890"
        (self.base / "keys").write_text(f"demo={secret}\n")
        output = io.StringIO()
        error = ValueError(f"Invalid header value b'Bearer {secret}\\r'")
        with patch.object(scio_common.OPENER, "open", side_effect=error), \
                patch.object(sys, "argv", ["register-models.py", "--show-claims"]), \
                redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            runpy.run_path(str(SCRIPTS / "register-models.py"), run_name="__main__")
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("could not reach", output.getvalue())
        self.assertNotIn(secret, output.getvalue())

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

    def run_release(self, diff_status=1, commit_status=0, fail_command=""):
        temporary = tempfile.TemporaryDirectory(prefix="release-", dir=self.base)
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        checkout = base / "checkout"
        shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", ".scio", ".remember", "__pycache__"))
        binaries = base / "bin"
        binaries.mkdir()
        log = base / "release-commands"
        commands = {
            "git": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$RELEASE_TEST_LOG"\n'
                   'case "$1" in commit) exit "$RELEASE_TEST_COMMIT";; diff) exit "$RELEASE_TEST_DIFF";; esac\n'
                   '[ "$1" != "$RELEASE_TEST_FAIL_COMMAND" ]\n',
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
                                         RELEASE_TEST_LOG=str(log), RELEASE_TEST_PYTHON=sys.executable,
                                         RELEASE_TEST_DIFF=str(diff_status), RELEASE_TEST_COMMIT=str(commit_status),
                                         RELEASE_TEST_FAIL_COMMAND=fail_command), timeout=15)
        return result, log.read_text().splitlines()

    def test_release_stops_before_tagging_when_commit_fails(self):
        result, seen = self.run_release(commit_status=1)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any(line.startswith("commit ") for line in seen), seen)
        self.assertFalse(any(line.startswith(("tag ", "push ", "gh release ")) for line in seen), seen)

    def test_release_tags_already_committed_files_without_empty_commit(self):
        result, seen = self.run_release(diff_status=0, commit_status=1)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(line.startswith("commit ") for line in seen), seen)
        self.assertTrue(any(line.startswith("tag -a v0.6.2 ") for line in seen), seen)
        self.assertTrue(any(line.startswith("gh release create v0.6.2 ") for line in seen), seen)

    def test_release_stops_when_staged_diff_cannot_be_read(self):
        result, seen = self.run_release(diff_status=128)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(line.startswith(("commit ", "tag ", "push ", "gh release ")) for line in seen), seen)

    def test_release_does_not_publish_after_tag_or_push_failure(self):
        for command in ("tag", "push"):
            with self.subTest(command=command):
                result, seen = self.run_release(fail_command=command)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(any(line.startswith("gh release ") for line in seen), seen)


if __name__ == "__main__":
    unittest.main()
