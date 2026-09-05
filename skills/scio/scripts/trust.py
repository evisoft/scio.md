#!/usr/bin/env python3
"""The operator's one-time consent to silent approvals — nothing is auto-approved until this has been granted.

  trust.py --status     is silent approval granted on this machine? (exit 0 = yes, 1 = no)
  trust.py --grant      grant it: the skill's hooks (Claude Code, Cursor, Antigravity) then approve, without a prompt,
                        Scio's own MCP tools (never scio_contest / scio_suspend), the skill's read-only scripts run from
                        the plugin, and fetches to scio.md. The deny guards (key in a tool argument, private addresses)
                        keep running either way. Everything else still follows the harness's normal permission flow.
  trust.py --revoke     back to asking.

The grant is a file (mode 600, dated) — $SCIO_TRUST_FILE, default `auto-approve` under ~/.config/scio — read by
auto-approve.py. SCIO_AUTO_APPROVE=1 in the environment grants it for one launch (fleets, containers).
Why a separate step: a plugin that turns off the prompts the moment it is installed is indistinguishable from a
malicious one; a plugin that asks once, in plain words, is not."""
import datetime, os, sys

WHAT = ("silent approval of: Scio's MCP tools (not scio_contest / scio_suspend), the skill's read-only scripts run from the "
        "plugin root, fetches to scio.md. Deny guards stay on. Revoke any time: trust.py --revoke (or /scio:trust off).")


def trust_path():
    return os.environ.get("SCIO_TRUST_FILE") or os.path.expanduser(os.path.join("~", ".config", "scio", "auto-approve"))


def granted():
    if os.environ.get("SCIO_AUTO_APPROVE", "").strip().lower() in ("1", "true", "yes"):
        return True
    try:
        return os.path.isfile(trust_path())
    except OSError:
        return False


if __name__ == "__main__":
    a = sys.argv[1:] or ["--status"]
    p = trust_path()
    if a[0] == "--grant":
        os.makedirs(os.path.dirname(p) or ".", mode=0o700, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"granted {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}\n{WHAT}\n")
        print(f"scio: silent approval granted ({p}). " + WHAT)
    elif a[0] == "--revoke":
        try:
            os.remove(p)
            print("scio: silent approval revoked; the harness asks again.")
        except FileNotFoundError:
            print("scio: silent approval was not granted.")
    else:
        g = granted()
        print("scio: silent approval is " + ("GRANTED — " + WHAT if g else "not granted: the harness's own prompts apply to every Scio tool call (grant with /scio:trust or trust.py --grant)."))
        sys.exit(0 if g else 1)
