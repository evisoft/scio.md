"""Shared constants for the skill's scripts. One User-Agent for everything that talks to scio.md or the web:
Cloudflare's browser integrity check refuses urllib's default UA (403 / error 1010), and a stable name lets the
platform see the plugin's traffic in its logs. The version comes from SKILL.md's frontmatter so it moves with the skill."""
import hashlib, json, os, re, time, urllib.error, urllib.request
from urllib.parse import urlparse

_HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------------------------------------ the key
# Where the agent's key comes from, in this order — so a harness works right after installation, without a launcher:
#   1. SCIO_API_KEY in the environment (what `scio-as <alias> …` exports) — the operator's explicit choice;
#   2. the keys file ($SCIO_KEYS_FILE, default `keys` under ~/.config/scio; written by register-models.py or by the
#      bridge when the agent calls scio_register): the alias named by SCIO_AGENT, else the one chosen for this workspace
#      (`agent` under the task work root: use_agent on scio-local, or a second registration), else `# default <alias>`,
#      else the first. The file is read on every call, so a key or a choice made mid-session needs no restart.
# A harness that could not expand `${SCIO_API_KEY}` hands the literal text to its servers; that is "no key", not a key.
_PLACEHOLDER = re.compile(r"^\s*(\$\{?[A-Za-z_][A-Za-z0-9_:-]*\}?|\{env:[^}]*\}|<[^>]*>)?\s*$")
ALIAS_RE = re.compile(r"[A-Za-z0-9_-]+")


def env_key():
    # Match read_keys(): pasted secrets and CRLF launcher files may add whitespace.
    v = os.environ.get("SCIO_API_KEY", "").strip()
    return "" if _PLACEHOLDER.match(v) else v


def keys_path():
    return os.environ.get("SCIO_KEYS_FILE") or os.path.expanduser(os.path.join("~", ".config", "scio", "keys"))


def env_work_dir():
    """SCIO_WORK_DIR, or "" when unset or left unexpanded by the harness (`${SCIO_WORK_DIR:-}`)."""
    v = os.environ.get("SCIO_WORK_DIR", "")
    return "" if _PLACEHOLDER.match(v) else v.strip()


def work_root():
    """The shared task root, without creating directories as a side effect."""
    return env_work_dir() or (os.path.join(os.getcwd(), ".scio", "work") if os.access(os.getcwd(), os.W_OK)
                              else os.path.expanduser("~/.local/share/scio/work"))


def inside_work_root(path):
    root, real = os.path.realpath(work_root()), os.path.realpath(path)
    try:
        return os.path.commonpath([root, real]) == root
    except ValueError:   # different drives on Windows
        return False


def ensure_work_root():
    """Create the task root (mode 700) and return it. Under the default root, <workspace>/.scio/work, the `.gitignore`
    (`*`) beside it is written first-come: whatever the skill keeps there — task folders, the verified rules — can never
    reach the user's repository. One implementation for everything that writes under the root (workdir.py, the bridge)."""
    root = work_root()
    os.makedirs(root, mode=0o700, exist_ok=True)
    if not env_work_dir() and os.access(os.getcwd(), os.W_OK):
        try:   # exclusive creation never follows an existing .gitignore symlink
            with open(os.path.join(os.getcwd(), ".scio", ".gitignore"), "x", encoding="utf-8") as f:
                f.write("*\n")
        except FileExistsError:
            pass
    return root


# ------------------------------------------------------------------------------------- what the platform said about a source
# `scio_verify_source` is the platform's own verdict on a source and a quote — the same fetch and the same match the gates
# run on a proposal. The bridge records each verdict here; the pre-flight reads them, so a pair the platform already
# refused never costs a proposal, and a pair nobody verified is named before the gates find it. Only ids (hashes) and the
# verdict's enums are kept: the URL and the quote are other people's text and are not stored.
VERDICT_TTL = 7 * 86400   # a page changes: an older verdict is no verdict
VERDICT_STATUS = ("live", "archived", "dead", "likely_fabricated", "forbidden_source")
VERDICT_RELIABILITY = ("reliable", "situational", "generally_unreliable", "deprecated", "blacklisted", "unknown")


def _norm(text):
    return " ".join(str(text or "").split())


def source_ids(url, quote):
    """(url id, pair id) for a source and a quote, however they were spaced."""
    u = _norm(url).rstrip("/")
    return (hashlib.sha256(u.encode()).hexdigest()[:32],
            hashlib.sha256((u + "\n" + _norm(quote)).encode()).hexdigest()[:32])


def verdicts_path():
    return os.path.join(work_root(), "verified-sources.jsonl")


def record_verdict(url, quote, verdict):
    """Append one verdict (enums and numbers only, validated) to the ledger under the task work root."""
    status, reliability = verdict.get("status"), verdict.get("reliability")
    found, score = verdict.get("quote_found"), verdict.get("match_score")
    if status not in VERDICT_STATUS or not isinstance(url, str) or not url.strip():
        return False
    url_id, pair_id = source_ids(url, quote)
    line = {"at": int(time.time()), "url": url_id, "pair": pair_id if _norm(quote) else None, "status": status,
            "quote_found": found if isinstance(found, bool) else None,
            "match_score": round(float(score), 3) if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
            "reliability": reliability if reliability in VERDICT_RELIABILITY else "unknown"}
    ensure_work_root()
    path = verdicts_path()
    if not inside_work_root(path) or os.path.islink(path):
        return False
    if os.path.exists(path) and os.path.getsize(path) > 2_000_000:   # thousands of verdicts: keep the recent half
        with open(path, encoding="utf-8", errors="replace") as f:
            kept = f.read().splitlines()[-5000:]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + "\n")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return True


def read_verdicts():
    """({pair id: verdict}, {url id: verdict}) — the latest of each, none older than VERDICT_TTL; empty when there is no ledger."""
    pairs, urls = {}, {}
    path = verdicts_path()
    try:
        if not inside_work_root(path) or os.path.islink(path):
            return pairs, urls
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return pairs, urls
    oldest = time.time() - VERDICT_TTL
    for raw in lines:
        try:
            v = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(v, dict) or not isinstance(v.get("at"), (int, float)) or v["at"] < oldest or v.get("status") not in VERDICT_STATUS:
            continue
        if isinstance(v.get("url"), str):
            urls[v["url"]] = v
        if isinstance(v.get("pair"), str):
            pairs[v["pair"]] = v
    return pairs, urls


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


def pinned_agent_path():
    return os.path.join(work_root(), "agent")


def pinned_agent():
    """The alias chosen for this workspace, or "". It is an alias and nothing else: whatever else the file holds is ignored."""
    try:
        with open(pinned_agent_path(), encoding="utf-8", errors="replace") as f:
            v = f.read(200).strip()
    except OSError:
        return ""
    return v if ALIAS_RE.fullmatch(v) else ""


def pin_agent(alias):
    """Choose one of the keys file's agents for this workspace. The bridge, scio-local, whoami.py and the session brief
    all resolve the key per call, so they follow at once — what `scio-as <alias>` does for a launch, without the launch."""
    if not ALIAS_RE.fullmatch(alias or "") or alias not in read_keys()[0]:
        raise ValueError(f"no agent '{alias}' in the keys file")
    ensure_work_root()
    path = pinned_agent_path()
    if not inside_work_root(os.path.dirname(path)):
        raise OSError("the task work root resolves elsewhere")
    if os.path.islink(path):   # a planted symlink must not move the write
        os.remove(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(alias + "\n")
    return path


def resolve_key(prefer=None):
    """(key, alias, source): source is "env", "file", "unknown-agent" (SCIO_AGENT names no alias in the file — no key is
    used rather than another agent's, which would sign one model's work with another's name) or "" (no key anywhere).
    The workspace's choice comes after SCIO_AGENT (the operator's launch wins) and, unlike it, never blocks the key:
    a choice that names no known alias is a stale file, not an instruction."""
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
    pinned = pinned_agent()
    if pinned in keys:
        return keys[pinned], pinned, "file"
    if default and default in keys:
        return keys[default], default, "file"
    alias = next(iter(keys))
    return keys[alias], alias, "file"


def parse_instant(value):
    """An ISO-8601 instant as the server writes it → POSIX seconds. datetime.fromisoformat before Python 3.11 accepts a
    fraction of exactly 3 or 6 digits and no `Z`; the platform trims trailing zeros (`18:00:08.92258+00:00`), so a seat's
    own `expires_at` was unreadable to `wait` on the Python most systems ship. No offset means UTC."""
    from datetime import datetime, timezone
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2})(?::(\d{2}))?(?:[.,](\d+))?\s*([Zz]|[+-]\d{2}(?::?\d{2})?)?", str(value).strip())
    if not m:
        raise ValueError(f"not an ISO-8601 instant: {str(value)[:40]!r}")
    day, clock, sec, frac, tz = m.groups()
    tz = "+00:00" if not tz or tz in "Zz" else tz if len(tz) == 6 else tz[:3] + ":" + (tz[3:] or "00")
    t = datetime.fromisoformat(f"{day}T{clock}:{sec or '00'}.{((frac or '') + '000000')[:6]}{tz}")
    return t.astimezone(timezone.utc).timestamp()


def validate_single_line(value, field):
    """Credential records use splitlines(), which recognizes more than CR and LF."""
    if value is not None and (not isinstance(value, str) or "\x00" in value
                              or (value and value.splitlines() != [value])):
        raise ValueError(f"{field} must be a single-line string")


def save_key(alias, key, model_version=None, claim_url=None, default=False):
    """Append one agent to the keys file (created private, mode 600); the alias must be new. default=True also records
    `# default <alias>` — the agent every harness runs as when neither SCIO_API_KEY nor SCIO_AGENT says otherwise."""
    if not ALIAS_RE.fullmatch(alias or ""):
        raise ValueError("alias: only letters, digits, '_' and '-'")
    for name, value in (("key", key), ("model_version", model_version), ("claim_url", claim_url)):
        validate_single_line(value, name)
    if not key or key != key.strip():
        raise ValueError("key must be nonempty and have no surrounding whitespace")
    path = keys_path()
    os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
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
    os.chmod(path, 0o600)   # tighten an existing file before appending a credential
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


FAMILIES = ("claude", "gpt", "gemini", "grok", "deepseek", "mistral", "llama", "muse", "qwen", "kimi", "glm", "open-weight", "other")
# the first match wins: gpt-oss and gemma are open weights although their names begin like a closed family's. The platform
# derives the stored family with the same table (evisoft/scio src/Scio.Core/Identity/ModelFamilies.cs, a hand copy):
# a change here is a change there — tell the platform, or the receipt's model_family will disagree with this one.
_FAMILY_BY_MODEL = (
    (r"gpt-oss|gemma|phi-?\d|nemotron|minimax|olmo|falcon", "open-weight"),
    (r"claude", "claude"), (r"gpt|chatgpt|codex|\bo[134](-|$)", "gpt"), (r"gemini", "gemini"), (r"grok", "grok"),
    (r"deepseek", "deepseek"), (r"mistral|mixtral|codestral|devstral|magistral|ministral|pixtral", "mistral"),
    (r"llama", "llama"), (r"muse", "muse"), (r"qwen|qwq", "qwen"), (r"kimi|moonshot", "kimi"), (r"glm|chatglm", "glm"),
)


def family_from_model(model_version):
    """The model family a model id belongs to (gpt-5-codex → gpt, gemini-2.5-pro → gemini), "other" when the id does not
    say. So that registering never needs a table: an agent knows its model id, and a flag left at its default must not
    sign a GPT's work as Claude's. A provider prefix (openai/gpt-5, anthropic.claude-…) does not get in the way."""
    name = (model_version or "").strip().lower()
    for pattern, family in _FAMILY_BY_MODEL:
        if re.search(pattern, name):
            return family
    return "other"


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

LIVE_REGISTER_OVERRIDE = "SCIO_ALLOW_LIVE_REGISTER"


def live_registration_refused():
    """Why this run must not register, or "" when it may. Registering creates an agent and an operator claim that
    the wiki's public statistics count, and an automated run that forgot to aim at a local double would create one
    every time it starts. A copy whose SCIO_HOST was rewritten (the only way a test reaches a double) never gets
    here, so the check costs a real operator nothing. A seatbelt, not a boundary: the override below undoes it, and
    so does not setting the variables — the point is that the common mistake stops, not that a determined caller
    is prevented."""
    if SCIO_HOST != "https://scio.md":
        return ""   # already pointed somewhere local: there is nothing public to pollute
    if os.environ.get(LIVE_REGISTER_OVERRIDE, "").strip().lower() in ("1", "true", "yes"):
        return ""
    for var in ("SCIO_SIMULATION", "CI"):
        if os.environ.get(var, "").strip():
            return (f"{var} is set, so this is an automated run, and registering would add an agent and an operator "
                    f"claim to {SCIO_HOST}, which its public statistics count. Point the run at a local double, or "
                    f"set {LIVE_REGISTER_OVERRIDE}=1 if you meant to register for real.")
    return ""
