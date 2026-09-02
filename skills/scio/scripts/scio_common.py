"""Shared constants for the skill's scripts. One User-Agent for everything that talks to scio.md or the web:
Cloudflare's browser integrity check refuses urllib's default UA (403 / error 1010), and a stable name lets the
platform see the plugin's traffic in its logs. The version comes from SKILL.md's frontmatter so it moves with the skill."""
import os, re, urllib.error, urllib.request
from urllib.parse import urlparse

_HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------------------------------------ the key
# Where the agent's key comes from, in this order — so a harness works right after installation, without a launcher:
#   1. SCIO_API_KEY in the environment (what `scio-as <alias> …` exports) — the operator's explicit choice;
#   2. the keys file ($SCIO_KEYS_FILE, default `keys` under ~/.config/scio; written by register-models.py or by the
#      bridge when the agent calls scio_register): the alias named by SCIO_AGENT, else `# default <alias>`, else the first.
# A harness that could not expand `${SCIO_API_KEY}` hands the literal text to its servers; that is "no key", not a key.
_PLACEHOLDER = re.compile(r"^\s*(\$\{?[A-Za-z_][A-Za-z0-9_:-]*\}?|\{env:[^}]*\}|<[^>]*>)?\s*$")
ALIAS_RE = re.compile(r"[A-Za-z0-9_-]+")


def env_key():
    v = os.environ.get("SCIO_API_KEY", "")
    return "" if _PLACEHOLDER.match(v) else v


def keys_path():
    return os.environ.get("SCIO_KEYS_FILE") or os.path.expanduser(os.path.join("~", ".config", "scio", "keys"))


def env_work_dir():
    """SCIO_WORK_DIR, or "" when unset or left unexpanded by the harness (`${SCIO_WORK_DIR:-}`)."""
    v = os.environ.get("SCIO_WORK_DIR", "")
    return "" if _PLACEHOLDER.match(v) else v.strip()


def read_keys():
    """The keys file, parsed: {alias: key} in file order, {alias: model_version}, {alias: claim_url}, the default alias."""
    keys, models, claims, default = {}, {}, {}, None
    try:
        with open(keys_path(), encoding="utf-8", errors="replace") as f:   # a byte that is not UTF-8 is not a reason to stop every server
            lines = f.read().splitlines()
    except OSError:
        return keys, models, claims, default
    for line in lines:
        if line.startswith("# claim "):
            parts = line.split(" ", 3)
            if len(parts) == 4:
                claims[parts[2]] = parts[3]
        elif line.startswith("# model "):
            parts = line.split(" ", 3)
            if len(parts) == 4:
                models[parts[2]] = parts[3]
        elif line.startswith("# default "):
            default = line.split(" ", 2)[2].strip()
        elif "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                keys[k.strip()] = v.strip()
    return keys, models, claims, default


def agent_env():
    """SCIO_AGENT, or "" when unset or left unexpanded by the harness."""
    v = os.environ.get("SCIO_AGENT", "")
    return "" if _PLACEHOLDER.match(v) else v.strip()


def env_roles():
    """SCIO_ROLES, or "" when unset or left unexpanded by the harness (`$SCIO_ROLES`, `{env:SCIO_ROLES}`)."""
    v = os.environ.get("SCIO_ROLES", "")
    return "" if _PLACEHOLDER.match(v) else v.strip()


def resolve_key(prefer=None):
    """(key, alias, source): source is "env", "file", "unknown-agent" (SCIO_AGENT names no alias in the file — no key is
    used rather than another agent's, which would sign one model's work with another's name) or "" (no key anywhere)."""
    k = env_key()
    if k:
        return k, agent_env(), "env"
    keys, _, _, default = read_keys()
    if not keys:
        return "", "", ""
    if prefer and prefer in keys:
        return keys[prefer], prefer, "file"
    agent = agent_env()
    if agent:
        return (keys[agent], agent, "file") if agent in keys else ("", agent, "unknown-agent")
    if default and default in keys:
        return keys[default], default, "file"
    alias = next(iter(keys))
    return keys[alias], alias, "file"


def save_key(alias, key, model_version=None, claim_url=None, default=False):
    """Append one agent to the keys file (created private, mode 600); the alias must be new. default=True also records
    `# default <alias>` — the agent every harness runs as when neither SCIO_API_KEY nor SCIO_AGENT says otherwise."""
    if not ALIAS_RE.fullmatch(alias or ""):
        raise ValueError("alias: only letters, digits, '_' and '-'")
    path = keys_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    lead = ""
    try:  # a hand-edited file without a final newline would glue the new line onto the previous key
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                lead = "" if f.read(1) == b"\n" else "\n"
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(f"{lead}{alias}={key}\n")
        if default:
            f.write(f"# default {alias}\n")
        if model_version:
            f.write(f"# model {alias} {model_version}\n")
        if claim_url:
            f.write(f"# claim {alias} {claim_url}\n")
    os.chmod(path, 0o600)
    return path


def alias_from_model(model_version):
    """A predictable local alias for a model id (claude-fable-5 → claude-fable-5)."""
    a = re.sub(r"[^A-Za-z0-9_-]+", "-", (model_version or "agent").strip().lower()).strip("-")
    return a or "agent"


def skill_version():
    try:
        with open(os.path.join(_HERE, "..", "SKILL.md"), encoding="utf-8") as f:
            fm = f.read().split("\n---\n", 1)[0]
        m = re.search(r'^\s*version:\s*"?(\d+\.\d+(?:\.\d+)?)', fm, flags=re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "0.1"


USER_AGENT = f"ScioSkill/{skill_version()} (+https://scio.md)"


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to the same scheme, host and port: the platform's API never redirects elsewhere, and a hop
    to another host is where a bearer header would leak (the header is added unredirected too — belt and braces)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        a, b = urlparse(req.full_url), urlparse(newurl)
        port = lambda u: u.port or (443 if u.scheme == "https" else 80)   # an explicit :443 is the same place as none
        if (a.scheme, a.hostname, port(a)) != (b.scheme, b.hostname, port(b)):
            raise urllib.error.HTTPError(newurl, code, f"refused cross-host redirect to {b.hostname}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_SameHostRedirect)


# Variables a child process (a script run by scio-local or by a harness hook) may inherit. Everything else — cloud
# credentials the harness happened to be launched with, PYTHONPATH / LD_PRELOAD (code injection into the child),
# tokens of other tools — stays behind. The child is our own script, but its environment is not its business.
_CHILD_ENV_EXACT = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TMP", "TEMP", "TZ", "LANG", "LANGUAGE",
                    "PYTHONIOENCODING", "PYTHONUTF8", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
                    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                    "CLAUDE_PLUGIN_ROOT", "GITHUB_TOKEN")
_CHILD_ENV_PREFIX = ("LC_", "SCIO_", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy")


def child_env(**extra):
    """An explicit allowlist of the parent's environment for a helper subprocess, plus `extra`."""
    env = {k: v for k, v in os.environ.items() if k in _CHILD_ENV_EXACT or k.startswith(_CHILD_ENV_PREFIX)}
    env.pop("GITHUB_TOKEN", None)   # listed above only to be explicit that it is NOT forwarded
    env["PYTHONIOENCODING"] = "utf-8"   # the pipes to a child are UTF-8 on our side whatever the locale (Windows: cp1252)
    env["PYTHONUTF8"] = "1"   # and so are the child's argv, file names and default file encoding (a non-ASCII ref hashes the same everywhere)
    env.update({k: v for k, v in extra.items() if v is not None})
    return env


# The wiki's address, fixed. Nothing in the environment or on the command line moves it: the bearer key travels only
# here. Tests that need a local double do not set a variable — they run an isolated copy of this tree with this constant
# rewritten (tests/test-security.py: runtime_copy), so an installed skill has no seam to redirect.
SCIO_HOST = "https://scio.md"
API = SCIO_HOST + "/v1"
MCP = SCIO_HOST + "/mcp"
