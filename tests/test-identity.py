#!/usr/bin/env python3
"""Regressions for the 23 Sep 2026 review — identity: setup.py (the modes of the configs it merges, what it says after a
failure, the interpreter it writes, a model already registered under another alias), rules verification without the
`cryptography` package, the rules bundle during a version's notice period, the session brief (source checks, a refused
key, rules published ahead of their date) and the unattended watch through a suspension.

Run: python3 tests/test-identity.py (test-security.py runs it too). Nothing leaves the machine: every script that talks
to the wiki runs from an isolated copy of the tree whose fixed address (scio_common.SCIO_HOST) points at a local double or
at a closed port — the same device as the other suites. setup.py runs from a copy too, because some harnesses make it
rewrite files of the tree it runs from."""
import base64
import hashlib
import http.server
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/scio"
SCRIPTS = SKILL / "scripts"
KEY = "sk_test_IDENTITY_KEY_0123456789"
CLOSED = "http://127.0.0.1:1"   # nothing listens there: a script that tries the network fails instead of reaching scio.md


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SCIO_") and k not in ("CLAUDE_PLUGIN_ROOT", "GITHUB_ACTIONS", "CI")}
    env.update({k: str(v) for k, v in extra.items()})
    return env


def copy_tree(dest, host=None, skill_only=False):
    """The repository (or, skill_only, skills/scio alone, as `npx skills add` installs it) under `dest`; with `host`, the
    copy's fixed wiki address points there. Returns the copy's root."""
    if skill_only:
        shutil.copytree(SKILL, dest / "skills/scio", ignore=shutil.ignore_patterns("__pycache__"))
    else:
        shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns(".git", ".scio", "__pycache__", "tests", "docs", "README*"))
    if host:
        common = dest / "skills/scio/scripts/scio_common.py"
        source = common.read_text(encoding="utf-8")
        assert 'SCIO_HOST = "https://scio.md"' in source
        common.write_text(source.replace('SCIO_HOST = "https://scio.md"', f'SCIO_HOST = "{host}"', 1), encoding="utf-8")
    return dest


def pin_key(skill, pub_b64):
    md = skill / "SKILL.md"
    md.write_text(re.sub(r'rules-signing-key: "ed25519:[^"]+"', f'rules-signing-key: "ed25519:{pub_b64}"', md.read_text(encoding="utf-8")), encoding="utf-8")


# ------------------------------------------------------------------------------------------------ Ed25519, for fixtures
# RFC 8032 §6, the signing half, written apart from the verifier under test: these tests must not need the package whose
# absence they test, and a signer that shared the verifier's code would prove nothing about it.
_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P


def _add(a, b):
    e, f = (a[1] - a[0]) * (b[1] - b[0]) % _P, (a[1] + a[0]) * (b[1] + b[0]) % _P
    g, h = 2 * a[3] * b[3] * _D % _P, 2 * a[2] * b[2] % _P
    return ((f - e) * (h - g) % _P, (h + g) * (f + e) % _P, (h - g) * (h + g) % _P, (f - e) * (f + e) % _P)


def _mul(s, point):
    acc = (0, 1, 1, 0)
    while s:
        if s & 1:
            acc = _add(acc, point)
        point, s = _add(point, point), s >> 1
    return acc


def _base():
    y = 4 * pow(5, _P - 2, _P) % _P
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * pow(2, (_P - 1) // 4, _P) % _P
    x = _P - x if x & 1 else x
    return (x, y, 1, x * y % _P)


_B = _base()


def _encode(point):
    zi = pow(point[2], _P - 2, _P)
    x, y = point[0] * zi % _P, point[1] * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _hq(data):
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % _Q


class Signer:
    def __init__(self, secret):
        h = hashlib.sha512(secret).digest()
        self.a = (int.from_bytes(h[:32], "little") & ((1 << 254) - 8)) | (1 << 254)
        self.prefix = h[32:]
        self.public = _encode(_mul(self.a, _B))
        self.pub_b64 = base64.b64encode(self.public).decode()

    def sign(self, message):
        r = _hq(self.prefix + message)
        big_r = _encode(_mul(r, _B))
        return big_r + ((r + _hq(big_r + self.public + message) * self.a) % _Q).to_bytes(32, "little")


# RFC 8032 §7.1, tests 1–3: (secret key, public key, message, signature)
RFC8032 = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60", "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb", "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7", "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]
SIGNER = Signer(b"scio identity tests: a throwaway fixture key")


def signed_doc(version, effective_at, text="Fixture constitution.", signer=SIGNER, in_force=None):
    """A rules document as GET /v1/rules?part=signed serves it: the canonical text, its signature, no display copy."""
    rules = {"version": version, "effective_at": effective_at, "constitution_markdown": f"# Constitution\n\n{text}\n"}
    canonical = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return {"version": version, "rules_version": in_force or version, "canonical": canonical, "part": "signed",
            "rules": {"note": "Not repeated in this part: `canonical` is the document."}, "signing_key_id": "fixture",
            "effective_at": effective_at, "signature": base64.b64encode(signer.sign(canonical.encode())).decode()}


# ------------------------------------------------------------------------------------------------ the local double
WIKI = {"me_status": 200, "me": {}, "rules": {}, "in_force": None, "asked": []}


class Wiki(http.server.BaseHTTPRequestHandler):
    """GET /v1/me and GET /v1/rules[?version=…][&part=…] as the platform answers them: every published version by name,
    the one in force without a name, and `rules_version` naming the one in force in either case."""

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/v1/me":
            status, body = WIKI["me_status"], WIKI["me"] if WIKI["me_status"] == 200 else {"error": "unauthorized"}
        elif url.path == "/v1/rules":
            version = (query.get("version") or [None])[0]
            WIKI["asked"].append((version, (query.get("part") or [None])[0]))
            doc = WIKI["rules"].get(version or WIKI["in_force"])
            status, body = (200, dict(doc, rules_version=WIKI["in_force"])) if doc is not None else (404, {"error": "not_found"})
        else:
            status, body = 404, {"error": "not_found"}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


SERVER = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Wiki)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
HOST = f"http://127.0.0.1:{SERVER.server_port}"


def me(**over):
    base = {"display_name": "claude-code/test/fable", "rank": 3, "operator": {"id": "op_x", "verified": True},
            "permissions": ["read", "propose", "review_small", "review_article"], "assignments": [],
            "reputation": {"points_lifetime": 1200},
            "quota": {"proposals_left_today": 5, "reviews_left_today": 7, "points_balance": 900},
            "rules_version": None, "next_rank": {"rank": 4, "missing": {}}, "claim_url": None}
    base.update(over)
    return base


class Scratch(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="scio-identity-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        WIKI.update(me_status=200, me=me(), rules={}, in_force=None, asked=[])


# ================================================================================================ setup.py
class SetupTests(Scratch):
    """setup.py merges the Scio servers into configs that belong to the user and often hold other servers' tokens."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="scio-identity-tree-"))
        cls.tree = copy_tree(cls.tmp / "tree", host=CLOSED)
        cls.setup_py = cls.tree / "skills/scio/scripts/setup.py"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setup(self, *args, home=None, setup_py=None, **env):
        home = home or self.base / "home"
        home.mkdir(parents=True, exist_ok=True)
        work = self.base / "workspace"
        work.mkdir(exist_ok=True)
        env = clean_env(HOME=str(home), SCIO_KEYS_FILE=str(self.base / "keys"), SCIO_TRUST_FILE=str(self.base / "trust"), **env)
        return subprocess.run([sys.executable, str(setup_py or self.setup_py), *args], capture_output=True, text=True, env=env,
                              cwd=work, timeout=60, stdin=subprocess.DEVNULL)

    CONFIGS = [("cursor", ".cursor/mcp.json", "mcpServers"), ("gemini", ".gemini/settings.json", "mcpServers"),
               ("opencode", ".config/opencode/opencode.json", "mcp")]
    if sys.platform.startswith("linux"):   # where VS Code keeps the user-level mcp.json on Linux
        CONFIGS.append(("copilot", ".config/Code/User/mcp.json", "servers"))

    def test_an_existing_private_config_keeps_its_mode(self):
        """ident-1 / guards-6: the merge wrote a new file at 0644 and replaced the user's 0600 one with it."""
        for harness, rel, servers in self.CONFIGS:
            with self.subTest(harness=harness):
                home = self.base / f"home-{harness}"
                path = home / rel
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"myTokens": {"GITHUB_TOKEN": "ghp_secret"}}))
                os.chmod(path, 0o600)
                r = self.setup("--harness", harness, "--yes", home=home)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                cfg = json.loads(path.read_text())
                self.assertEqual(cfg["myTokens"], {"GITHUB_TOKEN": "ghp_secret"})
                self.assertIn("scio", cfg[servers])
                self.assertEqual(oct(mode(path)), oct(0o600), f"{rel} was loosened")

    def test_a_config_keeps_whatever_mode_the_user_gave_it_and_a_new_one_is_private(self):
        home = self.base / "home"
        path = home / ".cursor/mcp.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        os.chmod(path, 0o640)
        self.assertEqual(self.setup("--harness", "cursor", "--yes", home=home).returncode, 0)
        self.assertEqual(oct(mode(path)), oct(0o640))   # neither widened nor narrowed: the file is the user's
        r = self.setup("--harness", "gemini", "--yes", home=home)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rel in (".gemini/settings.json", ".gemini/trustedFolders.json"):
            self.assertEqual(oct(mode(home / rel)), oct(0o600), f"a new {rel} is created private")

    def test_the_configs_that_were_kept_private_still_are(self):
        """Kimi's and Antigravity's configs were always narrowed to 600; keeping a file's mode must not undo that."""
        home = self.base / "home"
        for rel, harness in ((".kimi/mcp.json", "kimi-cli"), (".gemini/config/mcp_config.json", "antigravity")):
            with self.subTest(harness=harness):
                path = home / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")
                os.chmod(path, 0o644)
                r = self.setup("--harness", harness, "--yes", home=home)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(oct(mode(path)), oct(0o600))

    def test_a_planted_temporary_name_is_not_followed(self):
        home = self.base / "home"
        path = home / ".cursor/mcp.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        outside = self.base / "outside.txt"
        outside.write_text("untouched")
        os.symlink(outside, str(path) + ".tmp")
        self.assertEqual(self.setup("--harness", "cursor", "--yes", home=home).returncode, 0)
        self.assertEqual(outside.read_text(), "untouched")
        self.assertIn("scio", json.loads(path.read_text())["mcpServers"])

    def test_a_symlinked_config_stays_a_symlink(self):
        """A dotfile manager's link is written through, not replaced by a regular file."""
        home = self.base / "home"
        target = self.base / "dotfiles/cursor-mcp.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"mcpServers": {"gh": {"command": "gh-mcp"}}}))
        os.chmod(target, 0o600)
        link = home / ".cursor/mcp.json"
        link.parent.mkdir(parents=True)
        os.symlink(target, link)
        self.assertEqual(self.setup("--harness", "cursor", "--yes", home=home).returncode, 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual(set(json.loads(target.read_text())["mcpServers"]), {"gh", "scio", "scio-local"})
        self.assertEqual(oct(mode(target)), oct(0o600))

    def test_a_config_it_cannot_read_announces_no_next_step(self):
        """ident-7 (a): after 'not valid JSON … add the servers by hand' the operator was told to restart and ask for setup."""
        home = self.base / "home"
        (home / ".gemini").mkdir(parents=True)
        (home / ".gemini/settings.json").write_text('// my settings\n{"theme": "dark"}\n')
        r = self.setup("--harness", "gemini", "--yes", home=home)
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not valid JSON", out)
        self.assertNotIn("next:", out)
        self.assertEqual((home / ".gemini/settings.json").read_text(), '// my settings\n{"theme": "dark"}\n')

    def test_a_failed_registration_announces_no_next_step(self):
        r = self.setup("--harness", "codex", "--register", "u", "--models", "fable=claude-fable-5", "--yes")
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("registration failed", out)
        self.assertNotIn("next:", out)

    def test_a_skill_only_antigravity_install_writes_its_config_without_the_repository_snippets(self):
        """ident-7 (b): without --trust it exited 1 with '… or re-run without --trust' after writing the config."""
        tree = copy_tree(self.base / "agents", host=CLOSED, skill_only=True)
        setup_py = tree / "skills/scio/scripts/setup.py"
        home = self.base / "home"
        r = self.setup("--harness", "antigravity", "--yes", home=home, setup_py=setup_py)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("scio", json.loads((home / ".gemini/config/mcp_config.json").read_text())["mcpServers"])
        self.assertNotIn("without --trust", out)
        self.assertIn("antigravity/permissions.md", out)   # where the deny list lives, said instead of printed
        self.assertIn("next:", out)
        # with --trust the approval lists are the point, and a skill-only install has none: said before anything is written
        home2 = self.base / "home2"
        r = self.setup("--harness", "antigravity", "--trust", "--yes", home=home2, setup_py=setup_py)
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("skill-only install", out)
        self.assertNotIn("next:", out)
        self.assertFalse((home2 / ".gemini/config/mcp_config.json").exists())
        self.assertFalse((self.base / "trust").exists())

    def test_configs_name_the_interpreter_that_ran_setup(self):
        """ident-15: `python3` from PATH can be the Windows Store alias stub (exit 9009) or another interpreter altogether."""
        fake = self.base / "bin"
        fake.mkdir()
        stub = fake / "python3"
        stub.write_text("#!/bin/sh\necho 'Python was not found; run without arguments to install from the Microsoft Store' >&2\nexit 9009\n")
        stub.chmod(0o755)
        home = self.base / "home"
        r = self.setup("--harness", "cursor", "--yes", home=home, PATH=f"{fake}{os.pathsep}{os.environ.get('PATH', '')}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        servers = json.loads((home / ".cursor/mcp.json").read_text())["mcpServers"]
        for name in ("scio", "scio-local"):
            self.assertNotEqual(servers[name]["command"], str(stub))
            self.assertEqual(os.path.realpath(servers[name]["command"]), os.path.realpath(sys.executable))

    def already_registered(self):
        (self.base / "keys").write_text(f"claude-opus-5={KEY}\n# default claude-opus-5\n# model claude-opus-5 claude-opus-5\n")

    def register_models(self, models):
        return subprocess.run([sys.executable, str(self.tree / "skills/scio/scripts/register-models.py"), "--name", "vitalie",
                               "--harness", "codex", "--models", models], capture_output=True, text=True, timeout=30,
                              env=clean_env(SCIO_KEYS_FILE=str(self.base / "keys")))

    def test_a_model_registered_under_another_alias_counts_as_registered(self):
        """ident-6: register-models.py said 'the skill uses it', then exited 1, and setup.py wrote no config."""
        self.already_registered()
        r = self.register_models("opus=claude-opus-5")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("claude-opus-5", r.stdout)
        home = self.base / "home"
        r = self.setup("--harness", "codex", "--register", "vitalie", "--models", "opus=claude-opus-5", "--yes", home=home)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertNotIn("registration failed", out)
        self.assertIn("[mcp_servers.scio]", (home / ".codex/config.toml").read_text())
        self.assertIn("next:", out)

    def test_the_alias_setup_pins_is_the_one_that_has_the_key(self):
        """Where the alias matters (Hermes: the key goes into its own .env), the requested alias has no key; the existing one has."""
        self.already_registered()
        home = self.base / "home"
        r = self.setup("--harness", "hermes", "--register", "vitalie", "--models", "opus=claude-opus-5", "--yes", home=home,
                       PATH=str(self.base / "empty-path"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"SCIO_API_KEY={KEY}", (home / ".hermes/.env").read_text())

    def test_a_genuine_registration_failure_still_fails(self):
        self.already_registered()
        r = self.register_models("opus=claude-opus-5,sonnet=claude-sonnet-5")   # sonnet cannot reach the (closed) server
        self.assertNotEqual(r.returncode, 0)


# ================================================================================================ rules verification
class VerifyWithoutCryptographyTests(Scratch):
    """ident-2: without `cryptography`, a correctly signed document was called INVALID wherever openssl cannot do Ed25519."""

    def verifier(self):
        return load("identity_verify_rules", SCRIPTS / "verify-rules.py")

    def test_the_fixture_signer_matches_rfc_8032(self):
        for secret, public, message, signature in RFC8032:
            signer = Signer(bytes.fromhex(secret))
            self.assertEqual(signer.public.hex(), public)
            self.assertEqual(signer.sign(bytes.fromhex(message)).hex(), signature)

    def test_the_bundled_verifier_accepts_rfc_8032_and_refuses_every_forgery(self):
        verify = self.verifier().ed25519_verify
        for secret, public, message, signature in RFC8032:
            pub, msg, sig = bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)
            other = bytes.fromhex(next(p for _, p, _, _ in RFC8032 if p != public))
            self.assertTrue(verify(pub, msg, sig))
            self.assertFalse(verify(pub, msg + b"x", sig))
            self.assertFalse(verify(pub, msg, sig[:63] + bytes([sig[63] ^ 1])))
            s = int.from_bytes(sig[32:], "little") + _Q   # the same equation with a non-canonical scalar: malleability
            self.assertFalse(verify(pub, msg, sig[:32] + s.to_bytes(32, "little")))
            self.assertFalse(verify(pub, msg, sig[:63]))
            self.assertFalse(verify(pub[:31], msg, sig))
            self.assertFalse(verify(b"\xff" * 32, msg, sig))   # y ≥ p: not a point
            self.assertFalse(verify(other, msg, sig))

    def test_the_bundled_verifier_agrees_with_cryptography(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError:
            self.skipTest("cryptography not installed")
        verify = self.verifier().ed25519_verify
        message = json.dumps({"constitution_markdown": "Every sentence is a claim. " * 3000}).encode()
        signature = SIGNER.sign(message)
        Ed25519PublicKey.from_public_bytes(SIGNER.public).verify(signature, message)   # raises when the fixture is wrong
        self.assertTrue(verify(SIGNER.public, message, signature))

    def run_verify(self, doc):
        """verify-rules.py with `cryptography` hidden and an `openssl` that cannot do Ed25519, as on stock macOS (LibreSSL)."""
        shadow = self.base / "shadow/cryptography"
        shadow.mkdir(parents=True, exist_ok=True)
        (shadow / "__init__.py").write_text("raise ImportError('hidden by the test')\n")
        fake = self.base / "bin"
        fake.mkdir(exist_ok=True)
        (fake / "openssl").write_text("#!/bin/sh\necho 'pkeyutl: Unknown option: -rawin' >&2\nexit 1\n")
        (fake / "openssl").chmod(0o755)
        served = self.base / "served.json"
        served.write_text(json.dumps(doc))
        return subprocess.run([sys.executable, str(SCRIPTS / "verify-rules.py"), str(served), "--key", SIGNER.pub_b64],
                              capture_output=True, text=True, timeout=60, cwd=self.base,
                              env=clean_env(PYTHONPATH=str(self.base / "shadow"), PATH=f"{fake}{os.pathsep}{os.environ.get('PATH', '')}"))

    def test_a_valid_document_verifies_without_cryptography_or_a_capable_openssl(self):
        r = self.run_verify(signed_doc("2026-09-30", "2026-09-30T00:00:00Z"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok: rules 2026-09-30", r.stdout)

    def test_a_forged_document_is_still_invalid_without_cryptography(self):
        forged = dict(signed_doc("2026-09-30", "2026-09-30T00:00:00Z"), signature=base64.b64encode(b"\x01" * 64).decode())
        for doc in (forged, signed_doc("2026-09-30", "2026-09-30T00:00:00Z", signer=Signer(b"somebody else"))):
            r = self.run_verify(doc)
            self.assertEqual(r.returncode, 1)
            self.assertIn("INVALID", r.stdout + r.stderr)


# ================================================================================================ the rules bundle
A, A_AT = "2020-01-01", "2020-01-01T00:00:00Z"   # in force
C, C_AT = "2021-01-01", "2021-01-01T00:00:00Z"   # in force later
B, B_AT = "2099-01-01", "2099-01-01T00:00:00Z"   # published, in force only from its date


class RulesBundleTests(Scratch):
    """e2e-15 / TESTS-1: a published version takes effect three days later; the bundle, its CI check and the brief must
    come through that instant instead of turning red on it."""

    def setUp(self):
        super().setUp()
        self.skill = copy_tree(self.base / "tree", host=HOST, skill_only=True) / "skills/scio"
        pin_key(self.skill, SIGNER.pub_b64)
        WIKI["rules"] = {A: signed_doc(A, A_AT, "Text of A."), B: signed_doc(B, B_AT, "Text of B."), C: signed_doc(C, C_AT, "Text of C.")}
        WIKI["in_force"] = A

    def refresh(self, *args, **env):
        return subprocess.run([sys.executable, str(self.skill / "scripts/refresh-rules.py"), *args], capture_output=True, text=True,
                              timeout=120, cwd=self.base, env=clean_env(**env))

    def bundled(self):
        return re.search(r'rules-version:\s*"([^"]+)"', (self.skill / "SKILL.md").read_text()).group(1)

    def test_a_release_can_carry_the_next_rules_before_they_take_effect(self):
        self.assertEqual(self.refresh().returncode, 0)
        self.assertEqual(self.bundled(), A)
        r = self.refresh("--version", B)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn((B, "signed"), WIKI["asked"])
        self.assertEqual(self.bundled(), B)
        self.assertIn(f'BUNDLED_RULES = "{B}"', (self.skill / "scripts/whoami.py").read_text())
        rules_md = (self.skill / "references/rules.md").read_text()
        self.assertIn(f"# Constitution (rules version {B})", rules_md)
        self.assertIn("Text of B.", rules_md)
        self.assertIn(B_AT, r.stdout)   # says when they take effect
        # before the switch: the check passes on the prepared bundle, and a plain refresh (what release.sh runs) keeps it
        r = self.refresh("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("not yet in force", r.stdout)
        self.assertEqual(self.refresh().returncode, 0)
        self.assertEqual(self.bundled(), B, "the release script rolled a prepared release back")
        # the instant B takes effect the server's rules in force are the bundle's: nothing to do, nothing red
        WIKI["in_force"] = B
        r = self.refresh("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"bundle matches verified rules {B}", r.stdout)

    def test_rules_that_moved_past_the_bundle_warn_and_do_not_fail(self):
        self.assertEqual(self.refresh().returncode, 0)
        WIKI["in_force"] = C
        r = self.refresh("--check", GITHUB_ACTIONS="true")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WARNING", r.stdout)
        self.assertRegex(r.stdout, rf"(?m)^::warning::.*{C}")
        self.assertNotIn("::warning::", self.refresh("--check").stdout)   # the annotation only where GitHub reads it
        # … but the bundle's own text is still checked against the signed text of the version it names
        rules_md = self.skill / "references/rules.md"
        rules_md.write_text(rules_md.read_text() + "Tampered.\n")
        self.assertNotEqual(self.refresh("--check").returncode, 0)

    def test_what_must_never_pass_still_fails_the_check(self):
        self.assertEqual(self.refresh("--version", B).returncode, 0)
        with self.subTest(case="the rules in force carry a forged signature"):
            WIKI["rules"][A] = dict(WIKI["rules"][A], signature=base64.b64encode(b"\x02" * 64).decode())
            self.assertNotEqual(self.refresh("--check").returncode, 0)
            WIKI["rules"][A] = signed_doc(A, A_AT, "Text of A.")
        with self.subTest(case="the pending version the bundle names carries a forged signature"):
            WIKI["rules"][B] = dict(WIKI["rules"][B], signature=base64.b64encode(b"\x03" * 64).decode())
            self.assertNotEqual(self.refresh("--check").returncode, 0)
            WIKI["rules"][B] = signed_doc(B, B_AT, "Text of B.")
        with self.subTest(case="the bundle's text differs from the pending version's"):
            rules_md = self.skill / "references/rules.md"
            original = rules_md.read_text()
            rules_md.write_text(original.replace("Text of B.", "Text of somebody's wishes."))
            self.assertNotEqual(self.refresh("--check").returncode, 0)
            rules_md.write_text(original)
        with self.subTest(case="the bundle names a newer version the platform does not publish"):
            del WIKI["rules"][B]
            self.assertNotEqual(self.refresh("--check").returncode, 0)
            WIKI["rules"][B] = signed_doc(B, B_AT, "Text of B.")
        with self.subTest(case="the bundle names a newer version that should already be in force"):
            WIKI["rules"][B] = signed_doc(B, "2021-06-01T00:00:00Z", "Text of B.")
            self.assertNotEqual(self.refresh("--check").returncode, 0)
            WIKI["rules"][B] = signed_doc(B, B_AT, "Text of B.")
        self.assertEqual(self.refresh("--check").returncode, 0)

    def test_version_is_refused_when_it_cannot_be_the_next_rules(self):
        self.assertEqual(self.refresh().returncode, 0)
        WIKI["in_force"] = C
        before = (self.skill / "SKILL.md").read_text()
        for version in (A, "2098-01-01", "latest", "../rules"):
            with self.subTest(version=version):
                self.assertNotEqual(self.refresh("--version", version).returncode, 0)
                self.assertEqual((self.skill / "SKILL.md").read_text(), before, "nothing changes when the version is refused")
        self.assertNotEqual(self.refresh("--check", "--version", B).returncode, 0)


# ================================================================================================ the bridge on a pending version
class BridgePendingRulesTests(Scratch):
    """e2e-15: a verified document that takes effect later is published, not in force: the bridge must not say 'adopt'."""

    def answer(self, bridge, doc):
        with patch.dict(os.environ, {"SCIO_WORK_DIR": str(self.base / "work")}):
            return bridge.with_verified_rules({"structuredContent": doc, "content": []})["structuredContent"]

    def test_a_pending_version_is_verified_but_not_adopted(self):
        skill = copy_tree(self.base / "tree", host=CLOSED, skill_only=True) / "skills/scio"
        pin_key(skill, SIGNER.pub_b64)
        bridge = load("identity_bridge", skill / "server/scio_bridge.py")
        pending = self.answer(bridge, signed_doc(B, B_AT, in_force=A))
        self.assertTrue(pending["verified"], pending["report"])
        self.assertFalse(pending["in_force"])
        self.assertNotIn("Adopt these numbers", pending["next"])
        self.assertIn(B_AT, pending["next"])
        current = self.answer(bridge, signed_doc(A, A_AT))
        self.assertTrue(current["verified"], current["report"])
        self.assertTrue(current["in_force"])
        self.assertIn("Adopt these numbers", current["next"])


# ================================================================================================ the session brief
class BriefTests(Scratch):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="scio-identity-brief-"))
        cls.scripts = copy_tree(cls.tmp / "tree", host=HOST, skill_only=True) / "skills/scio/scripts"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def whoami(self, **env):
        keys = self.base / "keys"
        keys.write_text(f"fable={KEY}\n# default fable\n# model fable claude-fable-5\n")
        r = subprocess.run([sys.executable, str(self.scripts / "whoami.py")], capture_output=True, text=True, timeout=30, cwd=self.base,
                           env=clean_env(SCIO_KEYS_FILE=str(keys), SCIO_TRUST_FILE=str(self.base / "trust"), **env))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_brief_shows_the_source_checks_left_today(self):
        """ident-9 / e2e-13: the platform added the counter after an agent ran out of checks mid-draft without warning."""
        quota = {"proposals_left_today": 5, "reviews_left_today": 7, "points_balance": 900}
        WIKI["me"] = me(quota=dict(quota, verifications_left_today=3))
        self.assertIn("source checks 3", self.whoami())
        WIKI["me"] = me(quota=dict(quota, verifications_left_today=0))
        out = self.whoami()
        self.assertIn("source checks 0", out)
        self.assertIn("from its snapshot", out)   # a URL found live earlier today is checked again for free
        WIKI["me"] = me()   # an older server without the field: nothing invented
        self.assertNotIn("source checks", self.whoami())

    def test_a_refused_key_names_suspension_and_freeze_too(self):
        """ident-5: the platform answers a suspended or frozen agent with the same plain 401 as a revoked key."""
        WIKI["me_status"] = 401
        out = self.whoami()
        self.assertIn("rejected the key of alias 'fable' (HTTP 401)", out)
        self.assertIn("suspended", out)
        self.assertIn("frozen", out)
        self.assertNotIn(KEY, out)

    def test_rules_published_ahead_of_their_date_are_not_called_a_change(self):
        """e2e-15: a release that carries the next rules before they take effect must not tell every session they changed."""
        WIKI["me"] = me(rules_version="2026-09-20")
        out = self.whoami(SCIO_RULES_BUNDLED="2026-09-30")
        self.assertNotIn("rules changed", out)
        self.assertIn("not yet in force", out)
        self.assertIn("2026-09-20", out)
        WIKI["me"] = me(rules_version="2026-10-05")
        self.assertIn("rules changed (server 2026-10-05, bundled 2026-09-30)", self.whoami(SCIO_RULES_BUNDLED="2026-09-30"))


class SkillDocsTests(unittest.TestCase):
    def test_the_source_check_counter_is_where_the_agent_reads_its_quota(self):
        """e2e-13: SKILL.md's list of quota fields, roles.md's example and /scio:status left it out; write.md never said a
        check spends a daily allowance."""
        for path in (SKILL / "SKILL.md", ROOT / "commands/status.md", SKILL / "references/roles.md"):
            with self.subTest(file=str(path.relative_to(ROOT))):
                self.assertIn("verifications_left_today", path.read_text(encoding="utf-8"))
        write = (SKILL / "references/workflows/write.md").read_text(encoding="utf-8")
        self.assertIn("verifications_left_today", write)
        self.assertIn("from_snapshot", write)


# ================================================================================================ the unattended watch
class WatchTests(Scratch):
    """ident-5 / e2e-9: a suspension — a few hours — ended an unattended --watch for good."""

    REFUSED = (None, "refused: scio.md rejected the key (HTTP 401)")

    def drive(self, answers, polls=40, run_for=0):
        s = load("identity_supervise", SCRIPTS / "supervise.py")
        clock, sleeps, said, feed = [1_000_000.0], [], [], list(answers)

        class Done(Exception):
            pass

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
            if len(sleeps) >= polls:
                raise Done

        def fake_fetch():
            return feed.pop(0) if len(feed) > 1 else feed[0]

        with patch.object(s, "fetch_me", fake_fetch), patch.object(s, "run", lambda cmd, log: (0, "")), \
                patch.object(s.time, "sleep", fake_sleep), patch.object(s.time, "time", lambda: clock[0]), \
                patch.object(s, "say", said.append), patch.dict(os.environ, {"SCIO_ROLES": ""}):
            try:
                code = s.watch(["harness"], None, poll=300, tasks_every=0, run_for=run_for, max_rounds=0, max_restarts=10)
            except Done:
                code = None
        return code, sleeps, said

    def test_a_refused_key_is_checked_again_hourly_and_the_watch_gives_up_after_a_day(self):
        code, sleeps, said = self.drive([self.REFUSED])
        self.assertEqual(code, 3)
        self.assertEqual(sleeps, [3600] * 24)
        self.assertEqual(sum("suspended" in line for line in said), 1, "the reason is said once, not every hour")

    def test_the_watch_resumes_when_the_suspension_lifts(self):
        code, sleeps, said = self.drive([self.REFUSED, self.REFUSED, self.REFUSED, (me(), None)], polls=6)
        self.assertIsNone(code)   # still watching
        self.assertEqual(sleeps[:3], [3600] * 3)
        self.assertTrue(all(270 <= x <= 330 for x in sleeps[3:]), sleeps)   # back to the ordinary poll
        # a later refusal starts its own day, not the rest of the first one
        code, sleeps, said = self.drive([self.REFUSED] * 20 + [(me(), None)] + [self.REFUSED], polls=60)
        self.assertEqual(code, 3)
        self.assertEqual(sleeps.count(3600), 20 + 24)

    def test_the_watch_still_stops_at_once_without_a_key_and_honours_for(self):
        code, sleeps, said = self.drive([(None, "stop: no key — register first")])
        self.assertEqual((code, sleeps), (3, []))
        code, sleeps, said = self.drive([self.REFUSED], run_for=5400)
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [3600, 1800])

    def test_fetch_me_calls_a_401_a_refusal_not_a_stop(self):
        scripts = copy_tree(self.base / "tree", host=HOST, skill_only=True) / "skills/scio/scripts"
        keys = self.base / "keys"
        keys.write_text(f"fable={KEY}\n")
        WIKI["me_status"] = 401
        probe = ("import sys, json; sys.path.insert(0, %r); import supervise as s; m, why = s.fetch_me(); "
                 "print(json.dumps([bool(m), why]))" % str(scripts))
        r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=30, cwd=self.base,
                           env=clean_env(SCIO_KEYS_FILE=str(keys)))
        got, why = json.loads(r.stdout)
        self.assertFalse(got)
        self.assertTrue(why.startswith("refused: scio.md rejected the key"), why)
        self.assertNotIn(KEY, why)


if __name__ == "__main__":
    unittest.main()
