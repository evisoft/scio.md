#!/usr/bin/env python3
"""Verify a rules document served by scio_get_rules / GET /rules against the public key pinned in SKILL.md.

  verify-rules.py served.json            exit 0 and print the version when the signature is valid (and, for a version whose
                                         effective_at is still ahead, that it is not yet in force); exit 1 otherwise
  verify-rules.py served.json --key <b64> use another pinned key (tests, rotation)
  verify-rules.py served.json --out rules.verified.json   also write the parsed signed document — adopt that file

Why (P0, P9): the rules govern what you write, review and spend; a rules document that arrived over the network
is data until its signature checks against a key you already had. Adopt a newer rules_version only after this
passes. Uses the `cryptography` package when present, otherwise the Ed25519 verification of RFC 8032 written out below
in plain Python — never an external tool: the openssl on stock macOS (LibreSSL) cannot verify Ed25519, and reading its
refusal as a bad signature told every such agent that correctly signed rules were forged. Never trusts `signing_key_id`
alone — the key id selects a pinned key, it does not vouch for one. The platform signs with `RulesPublisher`
(canonical JSON: keys sorted, no whitespace); this script verifies over the served `canonical` bytes and checks
they parse to the document you are shown."""
import base64, binascii, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def pinned_key():
    with open(os.path.join(HERE, "..", "SKILL.md"), encoding="utf-8") as f:
        fm = f.read().split("\n---\n", 1)[0]
    m = re.search(r'rules-signing-key:\s*"ed25519:([A-Za-z0-9+/=]+)"', fm)
    if not m:
        sys.exit("no rules-signing-key pinned in SKILL.md")
    return m.group(1)


def _instant(v):
    """Compare timestamps by instant, not by spelling ('Z' vs '+00:00')."""
    if not isinstance(v, str):
        return v
    from datetime import datetime
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return v


# ------------------------------------------------------------------ Ed25519 verification, RFC 8032 §5.1.7 and §6
# The reference arithmetic in extended coordinates, verification only (no secret is ever handled here, so constant time
# does not matter). One ~40 KB rules document verifies in milliseconds.
_P = 2**255 - 19                                                  # the field prime
_L = 2**252 + 27742317777372353535851937790883648493              # the order of the base point
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    e, f = (a[1] - a[0]) * (b[1] - b[0]) % _P, (a[1] + a[0]) * (b[1] + b[0]) % _P
    g, h = 2 * a[3] * b[3] * _D % _P, 2 * a[2] * b[2] % _P
    return ((f - e) * (h - g) % _P, (h + g) * (f + e) % _P, (h - g) * (h + g) % _P, (f - e) * (f + e) % _P)


def _mul(s, point):
    acc = (0, 1, 1, 0)   # the neutral element
    while s > 0:
        if s & 1:
            acc = _add(acc, point)
        point, s = _add(point, point), s >> 1
    return acc


def _equal(a, b):   # x1/z1 == x2/z2 and y1/z1 == y2/z2
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    return _P - x if (x & 1) != sign else x


def _decompress(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


_BY = 4 * pow(5, _P - 2, _P) % _P
_BASE = (_recover_x(_BY, 0), _BY, 1, _recover_x(_BY, 0) * _BY % _P)


def ed25519_verify(public, message, signature):
    """True when `signature` (64 bytes) is a valid Ed25519 signature of `message` under `public` (32 bytes). A malformed
    key or signature is False, never an exception; a non-canonical scalar (S ≥ L) is refused, as RFC 8032 requires."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a, r = _decompress(public), _decompress(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a is None or r is None or s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _L
    return _equal(_mul(s, _BASE), _add(r, _mul(h, a)))


def verify(pub_b64, canonical, sig_b64):
    try:
        pub, sig = base64.b64decode(pub_b64), base64.b64decode(sig_b64)
    except (binascii.Error, ValueError, TypeError):
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:   # the plugin declares no dependency: the pure verification above is always there
        return ed25519_verify(pub, canonical.encode(), sig)
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, canonical.encode())
        return True
    except InvalidSignature:
        return False
    except Exception:   # a malformed key (ValueError), or a build without Ed25519 underneath (UnsupportedAlgorithm: OpenSSL < 1.1.1,
        return ed25519_verify(pub, canonical.encode(), sig)   # an old LibreSSL) — the verification above decides, it is complete


def pending_note(signed):
    """What to add when a verified document takes effect later: a version is published three days before its
    `effective_at` (P10) and GET /v1/rules?version=<v> serves it during that notice — valid, and not yet the rules."""
    sys.path.insert(0, HERE)
    from scio_common import parse_instant   # reads the platform's trimmed fractions, which fromisoformat before 3.11 does not
    import time
    try:
        if parse_instant(signed.get("effective_at")) <= time.time():
            return ""
    except ValueError:
        return ""
    return (f" — published, not yet in force until {signed.get('effective_at')}: the rules in force apply until then (scio_get_rules "
            "without `version` serves them); do not adopt these early")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__.strip()); sys.exit(2)
    with open(a[0], encoding="utf-8") as f:
        doc = json.load(f)
    key = a[a.index("--key") + 1] if "--key" in a else pinned_key()
    for f in ("canonical", "signature", "version"):
        if f not in doc:
            sys.exit(f"rules document lacks {f}: not adoptable")
    # The signed bytes must be the document you are shown — no signing one thing and serving another. The platform's
    # canonical form (keys sorted, no whitespace, its own string escaping) is not rebuilt here; the signed text is
    # parsed and compared as JSON to the readable fields, which is escaping-independent.
    try:
        signed = json.loads(doc["canonical"])
    except ValueError:
        sys.exit("canonical is not JSON: not adoptable")
    if not isinstance(signed, dict):
        sys.exit("canonical is not a JSON object: not adoptable")
    if signed.get("version") != doc["version"]:
        sys.exit("signed version differs from the served version: not adoptable")
    if doc.get("part") == "signed":   # the platform's `signed` part carries no display copy — only a note where it would be
        shown = doc.get("rules")
        if shown is not None and (not isinstance(shown, dict) or set(shown) & set(signed)):
            sys.exit("the signed part carries rules of its own beside the signed text: not adoptable")
    elif "rules" not in doc or signed != doc["rules"]:  # strict: the display copy must be exactly the signed document
        sys.exit("served rules differ from the signed document: not adoptable")
    if "effective_at" in doc and _instant(signed.get("effective_at")) != _instant(doc["effective_at"]):
        sys.exit("signed effective_at differs from the served one: not adoptable")
    if verify(key, doc["canonical"], doc["signature"]):
        out = a[a.index("--out") + 1] if "--out" in a else None
        if out:  # what the agent adopts is the parsed signed text, never the display copy
            # --out writes wherever the argument says; the only place this script may write is the task work root
            # (SCIO_WORK_DIR / workdir.py's root) — never ~/.bashrc, never the skill's own files (security.md §2.8)
            sys.path.insert(0, HERE)
            import importlib
            wd = importlib.import_module("workdir")
            real, root_real = os.path.realpath(out), os.path.realpath(wd.root)
            if os.path.commonpath([real, root_real]) != root_real:
                sys.exit(f"refused to write outside the task work root ({wd.root}): {out}")
            os.makedirs(os.path.dirname(real), exist_ok=True)
            with open(real, "w", encoding="utf-8") as f:
                json.dump(signed, f, indent=2, ensure_ascii=False)
        by = "the key given with --key (NOT the pinned key: adopt only what the pinned key signs)" if "--key" in a else f"pinned key ({doc.get('signing_key_id', '?')})"
        print(f"ok: rules {doc['version']} signed by {by}, effective {doc.get('effective_at')}"
              + (f"; verified document written to {out}" if out else "") + pending_note(signed))
        sys.exit(0)
    sys.exit("signature INVALID: do not adopt these rules; report with scio_report")


if __name__ == "__main__":
    main()
