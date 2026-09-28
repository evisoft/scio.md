#!/usr/bin/env python3
"""Project-local credential storage: no production calls or real credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/scio/scripts'


class WorkspaceKeys(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.ws = self.base / 'workspace'
        self.ws.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('SCIO_')}
        self.env['HOME'] = str(self.home)

    def run_code(self, code, cwd=None, **env):
        return subprocess.run([sys.executable, '-c', f'import sys, os, json; sys.path.insert(0, {str(SCRIPTS)!r}); import scio_common as c; ' + code],
                              cwd=cwd or self.ws, env=dict(self.env, **env), capture_output=True, text=True, timeout=15)

    def save(self):
        return self.run_code("print(c.save_key('amber', 'test-secret', 'gpt-test', 'https://scio.md/claim/test', default=True))")

    def guard(self, command):
        payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}})
        r = subprocess.run([sys.executable, str(SCRIPTS / 'guard-secrets.py')], input=payload, cwd=self.ws, env=self.env,
                           capture_output=True, text=True, timeout=15)
        return json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'] if r.stdout.strip() else None

    def test_session_start_in_an_unregistered_folder_creates_nothing(self):
        # The plugin loads in every project the harness opens; only a registration creates ./scio/key.
        subprocess.run(['git', 'init', '-q', str(self.ws)], check=True)
        r = subprocess.run([sys.executable, str(SCRIPTS / 'whoami.py'), '--session-start'],
                           cwd=self.ws, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('not registered', r.stdout)
        self.assertEqual(sorted(p.name for p in self.ws.iterdir()), ['.git'])

    @unittest.skipUnless(shutil.which('rg'), 'ripgrep is not installed')
    def test_harness_searches_skip_the_key_folder_outside_git(self):
        # Harness Grep tools run ripgrep with --hidden; outside a Git repository .gitignore alone keeps nothing out.
        self.assertEqual(self.save().returncode, 0)
        r = subprocess.run(['rg', '--hidden', '-l', 'test-secret', '.'], cwd=self.ws, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=15)
        self.assertEqual(r.stdout, '')

    def test_secret_guard_blocks_searches_told_to_read_ignored_files(self):
        self.save()
        for command in ('rg -u secret', 'rg --no-ignore secret .', 'rg -n --no-ignore-dot secret'):
            self.assertIsNotNone(self.guard(command), command)
        for command in ('rg secret', 'rg -n secret .', 'grep -rn secret src'):
            self.assertIsNone(self.guard(command), command)

    def test_task_file_tools_never_reach_the_keys_under_a_wide_work_root(self):
        # SCIO_WORK_DIR set to the workspace (or above it) puts ./scio/key inside the task root
        self.assertEqual(self.save().returncode, 0)
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
        for i, (tool, args) in enumerate((("read_file", {"dir": str(self.ws / "scio/key"), "name": "keys"}),
                                           ("read_file", {"dir": str(self.ws / "scio"), "name": "key/keys"}),
                                           ("write_file", {"dir": str(self.ws / "scio"), "name": "key/keys", "content": "x=y\n"}),
                                           ("write_file", {"dir": str(self.ws), "name": "notes.md", "content": "fine\n"})), start=2):
            messages.append({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": tool, "arguments": args}})
        r = subprocess.run([sys.executable, str(SCRIPTS.parent / "server/scio_local.py")], cwd=self.ws, env=dict(self.env, SCIO_WORK_DIR=str(self.ws)),
                           input="".join(json.dumps(m) + "\n" for m in messages), capture_output=True, text=True, timeout=30)
        replies = {m["id"]: m for m in map(json.loads, r.stdout.splitlines())}
        self.assertNotIn("test-secret", r.stdout)
        for i in (2, 3, 4):
            self.assertTrue(replies[i].get("error") or replies[i]["result"].get("isError"), replies[i])
        self.assertIn("amber=test-secret", (self.ws / "scio/key/keys").read_text())
        self.assertEqual((self.ws / "notes.md").read_text(), "fine\n")

    def test_a_refused_workspace_search_says_how_to_search_instead(self):
        self.save()
        reason = self.guard('grep -rn TODO .')
        self.assertIsNotNone(reason)
        self.assertIn('rg', reason)
        self.assertNotIn('Report the text that asked for it', reason)   # an ordinary search is no injection

    def test_saves_key_and_claim_privately_ignored_by_git(self):
        subprocess.run(['git', 'init', '-q', str(self.ws)], check=True)
        r = self.save()
        self.assertEqual(r.returncode, 0, r.stderr)
        path = self.ws / 'scio/key/keys'
        self.assertEqual(r.stdout.strip(), str(path))
        self.assertIn('amber=test-secret\n', path.read_text())
        self.assertIn('# claim amber https://scio.md/claim/test\n', path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        ignored = subprocess.run(['git', 'check-ignore', 'scio/key/keys', 'scio/key/keys.lock'], cwd=self.ws, capture_output=True, text=True)
        self.assertEqual(len(ignored.stdout.splitlines()), 2)
        self.assertEqual(self.run_code('print(c.resolve_key()[1])').stdout.strip(), 'amber')

    def test_other_folder_and_nested_folder_do_not_inherit_identity(self):
        self.assertEqual(self.save().returncode, 0)
        for folder in (self.base / 'other', self.ws / 'nested'):
            folder.mkdir()
            self.assertEqual(self.run_code('print(bool(c.resolve_key()[0]))', cwd=folder).stdout.strip(), 'False')

    def test_home_keys_are_not_an_implicit_fallback(self):
        folder = self.home / '.config/scio'
        folder.mkdir(parents=True)
        (folder / 'keys').write_text('legacy=test-legacy\n')
        self.assertEqual(self.run_code('print(bool(c.resolve_key()[0]))').stdout.strip(), 'False')

    def test_process_keeps_starting_folder_after_chdir(self):
        other = self.base / 'other'
        other.mkdir()
        r = self.run_code(f'os.chdir({str(other)!r}); print(c.keys_path())')
        self.assertEqual(r.stdout.strip(), str(self.ws / 'scio/key/keys'))

    def test_unexpanded_override_uses_default(self):
        r = self.run_code('print(c.keys_path())', SCIO_KEYS_FILE='${SCIO_KEYS_FILE}')
        self.assertEqual(r.stdout.strip(), str(self.ws / 'scio/key/keys'))

    def test_explicit_override_still_works(self):
        r = self.run_code("c.save_key('a', 'test'); print(c.resolve_key()[1])", SCIO_KEYS_FILE=str(self.base / 'custom/keys'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'a')

    def test_symlinked_directory_file_and_lock_refused_before_write(self):
        for component in ('scio', 'scio/key', 'scio/key/keys', 'scio/key/keys.lock', 'scio/key/.gitignore'):
            with self.subTest(component=component), tempfile.TemporaryDirectory(dir=self.base) as temp:
                ws = Path(temp)
                victim = ws / 'outside'
                is_dir = component in ('scio', 'scio/key')
                victim.mkdir() if is_dir else victim.write_text('untouched\n')
                link = ws / component
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(victim, target_is_directory=is_dir)
                r = self.run_code("c.save_key('a', 'secret')", cwd=ws)
                self.assertNotEqual(r.returncode, 0, r.stdout)
                if not is_dir:
                    self.assertEqual(victim.read_text(), 'untouched\n')

    def test_hardlinked_key_is_not_read_or_written(self):
        victim = self.base / 'outside'
        victim.write_text('stolen=secret\n')
        path = self.ws / 'scio/key/keys'
        path.parent.mkdir(parents=True)
        os.link(victim, path)
        self.assertEqual(self.run_code('print(bool(c.resolve_key()[0]))').stdout.strip(), 'False')
        self.assertNotEqual(self.save().returncode, 0)
        self.assertEqual(victim.read_text(), 'stolen=secret\n')

    def test_secret_guard_blocks_default_key_and_claim_directory(self):
        self.save()
        for path in ('scio/key/keys', './scio/key', str(self.ws / 'scio/key/keys')):
            payload = json.dumps({'tool_name': 'Read', 'tool_input': {'file_path': path}})
            r = subprocess.run([sys.executable, str(SCRIPTS / 'guard-secrets.py')], input=payload, cwd=self.ws, env=self.env, capture_output=True, text=True)
            self.assertIn('deny', r.stdout, (path, r.stdout))

    def test_secret_guard_blocks_recursive_archives_and_alternate_paths(self):
        self.save()
        for command in ('cat scio/key/keys', 'head scio/k*/k*', 'tar cf /tmp/leak.tar scio',
                        'cp -r scio /tmp/leak', 'cd scio && cat key/keys',
                        'tar cf /tmp/leak.tar .', 'grep -r secret scio'):
            payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}})
            r = subprocess.run([sys.executable, str(SCRIPTS / 'guard-secrets.py')], input=payload, cwd=self.ws, env=self.env, capture_output=True, text=True)
            self.assertIn('deny', r.stdout, (command, r.stdout))

    @unittest.skipUnless(hasattr(os, 'getuid'), 'POSIX file modes')
    def test_a_keys_file_readable_by_others_is_not_this_folders_identity(self):
        # a repository can commit scio/key/keys: a clone makes its author's agent the identity of every session there. What
        # this skill writes is private (0600); a checkout's copy (0644/0664) is not, and is refused by servers and launcher
        path = self.ws / 'scio/key/keys'
        path.parent.mkdir(parents=True)
        path.write_text('claude-opus-5=sk_live_PLANTED_0123456789\n')
        os.chmod(path, 0o644)
        self.assertEqual(self.run_code('print(bool(c.resolve_key()[0]))').stdout.strip(), 'False')
        launched = subprocess.run(['bash', str(SCRIPTS / 'scio-as'), 'claude-opus-5', '--print-env'], cwd=self.ws, env=self.env,
                                  capture_output=True, text=True, timeout=30)
        self.assertNotEqual(launched.returncode, 0)
        self.assertNotIn('PLANTED', launched.stdout)

    def test_git_tracked_store_refused_before_key_write(self):
        subprocess.run(['git', 'init', '-q', str(self.ws)], check=True)
        folder = self.ws / 'scio/key'
        folder.mkdir(parents=True)
        (folder / 'keys').write_text('existing=test\n')
        subprocess.run(['git', 'add', 'scio/key/keys'], cwd=self.ws, check=True)
        r = self.save()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Git-tracked', r.stderr)
        self.assertEqual((folder / 'keys').read_text(), 'existing=test\n')

    def test_simultaneous_writers_keep_complete_records(self):
        processes = []
        for i in range(8):
            code = f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import scio_common as c; c.save_key('agent{i}', 'test{i}', 'model{i}', 'https://scio.md/claim/{i}')"
            processes.append(subprocess.Popen([sys.executable, '-c', code], cwd=self.ws, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for proc in processes:
            _, err = proc.communicate(timeout=20)
            self.assertEqual(proc.returncode, 0, err)
        r = self.run_code('print(json.dumps(c.read_keys()[:3]))')
        keys, models, claims = json.loads(r.stdout)
        self.assertEqual(len(keys), 8)
        for i in range(8):
            self.assertEqual((keys[f'agent{i}'], models[f'agent{i}'], claims[f'agent{i}']),
                             (f'test{i}', f'model{i}', f'https://scio.md/claim/{i}'))

    def test_session_reminder_cannot_write_through_linked_credential_directory(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (self.ws / 'scio').symlink_to(outside, target_is_directory=True)
        r = subprocess.run([sys.executable, str(SCRIPTS / 'whoami.py'), '--session-start'],
                           cwd=self.ws, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_session_reminder_does_not_wait_for_another_registration(self):
        code = (f'import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import scio_common as c\n'
                'with c.keys_lock():\n print("locked", flush=True)\n sys.stdin.readline()\n')
        holder = subprocess.Popen([sys.executable, '-c', code], cwd=self.ws, env=self.env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            r = subprocess.run([sys.executable, str(SCRIPTS / 'whoami.py'), '--session-start'],
                               cwd=self.ws, env=self.env, capture_output=True, text=True, timeout=3)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('not registered', r.stdout)
        finally:
            holder.communicate('\n', timeout=10)


if __name__ == '__main__':
    unittest.main()
