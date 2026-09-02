#!/usr/bin/env python3
"""One command per harness: register the two Scio MCP servers (scio, scio-local) with absolute paths, trusted where the
harness supports it, merged into the harness's existing config. Replaces hand-editing JSON/TOML and the `~` in
args arrays that most harnesses do not expand.

  setup.py --harness codex|gemini|kimi|kimi-cli|cursor|copilot|opencode|windsurf|antigravity|claude|hermes|openclaw|grok [--alias <alias>] [--workspace]
           [--trust] [--yes] [--register <user> --models alias=model_version,… [--family claude]]   # register the agents first, in one go

It first lists every file it is about to write or merge and asks (interactive) or requires --yes (an agent runs it only
after showing that list to the user). By default the harness's own permission prompts stay on for every Scio tool call;
--trust additionally writes the harness's "approve Scio's tools without a prompt" settings (never scio_contest /
scio_suspend) — the same one-time consent as `/scio:trust` in Claude Code, revocable by editing the file it names.

Both servers are local (scio_bridge.py relays to https://scio.md/mcp; scio_local.py does the local work) and find the key
themselves: SCIO_API_KEY when a launcher exported it, else the keys file written at registration — so a harness works
right after install, with no launcher. --alias pins one agent (SCIO_AGENT) in configs that cannot read the environment
(Antigravity, OpenClaw, Hermes) when several are registered; `scio-as <alias> <command>` does the same per launch.
--workspace writes the project-level file where the harness has one (Cursor, Copilot, Antigravity). Prints what it wrote."""
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SERVER = os.path.join(SKILL, "server", "scio_local.py")
BRIDGE = os.path.join(SKILL, "server", "scio_bridge.py")
PY = shutil.which("python3") or sys.executable
ROOT = os.path.dirname(os.path.dirname(SKILL))   # the plugin / repo root


def write_hooks_absolute(path, deny_json):
    """Rewrite a harness hooks file so every guard runs by absolute path and a guard that cannot start answers deny:
    Cursor and Antigravity run hook commands from the workspace, where `python3 skills/scio/scripts/x.py` does not
    exist — the adapter would never start and the harness would fall through to allow."""
    if not os.path.exists(path):
        return
    txt = open(path, encoding="utf-8").read()
    def fix(m):
        cmd = json.loads('"' + m.group(1) + '"')   # the real command, not its JSON spelling: re-encoding an escaped string doubles every backslash
        cmd = re.sub(r"^python3 (?:\S*/)?skills/scio/scripts/(\S+?\.py)(?:\s*\|\|.*)?$", lambda mm: f'python3 "{os.path.join(ROOT, "skills", "scio", "scripts", mm.group(1))}"', cmd)
        if "hook.py" in cmd and "||" not in cmd:
            cmd += " || echo '" + deny_json.replace("'", "") + "'"
        return '"command": ' + json.dumps(cmd)
    txt = re.sub(r'"command":\s*"((?:[^"\\]|\\.)*)"', fix, txt)
    open(path, "w", encoding="utf-8").write(txt)
    print(f"rewrote {path} with absolute guard paths")
SCRIPTS = os.path.join(SKILL, "scripts")


def render(path, escape=None):
    """A permission snippet with the placeholder __SCIO_SCRIPTS__ replaced by the absolute scripts directory —
    escaped for the harness's pattern language (a regex in VS Code and Antigravity, a glob in OpenCode). Only the
    absolute directory is approved: a wildcard prefix would approve a planted /tmp/x/skills/scio/scripts/x.py too."""
    if not os.path.exists(path):   # a skill-only install (npx skills add, ClawHub) carries skills/scio alone, not the repository's snippets
        sys.exit(f"{os.path.relpath(path, ROOT)} is not here: this is a skill-only install. Clone https://github.com/evisoft/scio.md and run setup.py from it for this option, or re-run without --trust.")
    txt = open(path, encoding="utf-8").read()
    return txt.replace("__SCIO_SCRIPTS__", escape(SCRIPTS) if escape else SCRIPTS)


def opencode_bash_rules():
    """The bash permission rules of opencode/opencode.scio.jsonc with absolute paths, as a dict (first match wins)."""
    txt = "\n".join(l for l in render(os.path.join(ROOT, "opencode", "opencode.scio.jsonc")).splitlines() if not l.strip().startswith("//"))
    return json.loads(txt)["permission"]["bash"]

ap = argparse.ArgumentParser()
ap.add_argument("--harness", required=True, choices=["codex", "gemini", "kimi", "kimi-cli", "cursor", "copilot", "opencode", "windsurf", "antigravity", "claude", "hermes", "openclaw", "grok"])
ap.add_argument("--alias")
ap.add_argument("--workspace", action="store_true")
ap.add_argument("--register", metavar="NAME", help="also register agents first: --register <user> --models alias=model,…")
ap.add_argument("--models")
ap.add_argument("--family", default="claude")
ap.add_argument("--trust", action="store_true", help="also switch off the harness's prompts for Scio's own tools (the operator's explicit consent)")
ap.add_argument("--yes", action="store_true", help="write without asking (the caller has shown the user the list of files)")
a = ap.parse_args()


def confirm(paths, extra=""):
    """Say what will be written, then ask — or require --yes when there is nobody to ask."""
    print("setup.py will write or merge:\n  " + "\n  ".join(os.path.abspath(x) for x in paths) + (("\n  " + extra) if extra else ""))
    print("  approvals: " + ("Scio's own tools approved WITHOUT a prompt (--trust; scio_contest/scio_suspend still ask)" if a.trust
                             else "the harness's normal prompts apply to every Scio tool call (add --trust to change that)"))
    if a.yes:
        return
    if not sys.stdin.isatty():
        sys.exit("nothing written: re-run with --yes after showing the user the list above")
    if input("continue? [y/N] ").strip().lower() not in ("y", "yes"):
        sys.exit("nothing written")

TRUST_FILE = os.environ.get("SCIO_TRUST_FILE") or os.path.expanduser(os.path.join("~", ".config", "scio", "auto-approve"))
if a.register:
    if not a.models:
        sys.exit("--register needs --models alias=model_version,…")
    sys.path.insert(0, HERE)
    from scio_common import keys_path as _keys_path
    confirm([_keys_path()], f"(registers {a.models.count('=') or 1} agent(s) on https://scio.md as {a.register} before writing the harness config)")
    a.yes = True   # the one question covers the files below too
    r = subprocess.run([sys.executable, os.path.join(HERE, "register-models.py"), "--name", a.register, "--family", a.family,
                        "--harness", a.harness, "--models", a.models])
    if r.returncode not in (0,):
        sys.exit("registration failed; fix that first")
    if not a.alias:
        a.alias = a.models.split(",")[0].split("=")[0].strip()


def merge_json(path, mutate, mode=0o600):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cfg = {}
    if os.path.exists(path):
        try:
            cfg = json.load(open(path, encoding="utf-8"))
        except ValueError:
            sys.exit(f"{path} is not valid JSON (comments?); add the servers by hand — see the snippet in the repository")
    mutate(cfg)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)
    print(f"wrote {path}")


def strip_toml_tables(text, prefixes):
    """Remove every TOML table whose header starts with one of `prefixes` (e.g. `[mcp_servers.scio]`,
    `[mcp_servers.scio.tools.x]`, `[profiles.scio]`), up to the next table header — whoever wrote them.
    Needed because Codex/Kimi refuse a duplicate table, and users often have an older hand-written or
    `codex mcp add` entry for the same server."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            name = stripped[1:].split("]", 1)[0].replace('"', "").replace("'", "").replace(" ", "")   # [mcp_servers."scio-local"] # note
            skipping = any(name == pfx or name.startswith(pfx + ".") for pfx in prefixes)
        elif stripped.startswith("[["):
            skipping = False
        if not skipping:
            out.append(line)
    return "".join(out)


def key_for(alias):
    sys.path.insert(0, HERE)
    from scio_common import read_keys, keys_path
    key = read_keys()[0].get(alias)
    if not key:
        sys.exit(f"no key for '{alias}' in {keys_path()}; register first (scio_register in a harness, or register-models.py)")
    return key


h = a.harness
if h == "claude":
    print("Claude Code needs nothing written: the plugin's .mcp.json registers both servers. Launch `claude` and say /scio:register "
          "(or /scio:status once registered); `scio-as <alias> claude` only to pick one of several agents.")
    if a.trust:
        confirm([os.environ.get("SCIO_TRUST_FILE") or os.path.expanduser(os.path.join("~", ".config", "scio", "auto-approve"))])
        subprocess.run([sys.executable, os.path.join(HERE, "trust.py"), "--grant"], check=False)
    else:
        print("Every Scio tool call goes through Claude Code's normal prompt until the user grants /scio:trust (or setup.py --harness claude --trust).")
elif h == "codex":
    path = os.path.expanduser("~/.codex/config.toml")
    prof = os.path.expanduser("~/.codex/scio.config.toml")
    confirm([path, prof])
    approve = 'default_tools_approval_mode = "approve"\n' if a.trust else ""   # without --trust Codex asks per tool, as for any server
    block = f'''
# --- Scio (written by setup.py) ---
[mcp_servers.scio]
command = {json.dumps(PY)}
args = [{json.dumps(BRIDGE)}, "--harness", "codex"]
env_vars = ["SCIO_API_KEY", "SCIO_AGENT", "SCIO_KEYS_FILE", "SCIO_ROLES"]   # forwarded from the launcher's environment when set (Codex starts servers with a minimal environment); the bridge otherwise reads the keys file
tool_timeout_sec = 120
{approve}
[mcp_servers.scio-local]
command = {json.dumps(PY)}
args = [{json.dumps(SERVER)}]
env_vars = ["SCIO_API_KEY", "SCIO_AGENT", "SCIO_KEYS_FILE", "SCIO_WORK_DIR", "SCIO_ROLES"]   # forwarded from the launcher's environment (documented key; a literal "$VAR" in `env` is not expanded)
tool_timeout_sec = 120
{approve}
[mcp_servers.scio.tools.scio_contest]
approval_mode = "prompt"

[mcp_servers.scio.tools.scio_suspend]
approval_mode = "prompt"

[mcp_servers.scio.tools.scio_register]
approval_mode = "prompt"

# --- end Scio ---
'''
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cur = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    cur = re.sub(r"\n?# --- Scio \(written by setup\.py\) ---.*?# --- end Scio ---\n", "\n", cur, flags=re.S)
    cur = strip_toml_tables(cur, ["mcp_servers.scio", "mcp_servers.scio-local", "profiles.scio"])  # older entries, whoever wrote them
    open(path, "w", encoding="utf-8").write(cur.rstrip("\n") + "\n" + block)
    # Codex ≥ 0.150 keeps each profile in its own file, ~/.codex/<profile>.config.toml (a [profiles.x] table is refused).
    open(prof, "w", encoding="utf-8").write(f'''# Scio profile for Codex (written by setup.py): codex --profile scio
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[sandbox_workspace_write]
network_access = true
writable_roots = [{json.dumps(os.path.expanduser('~/.local/share/scio'))}]   # task folders only; the keys directory stays read-only (JSON escaping is TOML escaping: Windows paths survive)
''')
    print(f"wrote {path} and {prof}; launch: codex --profile scio (scio-as <alias> codex --profile scio to pick one of several agents)")
elif h == "gemini":
    path = os.path.expanduser("~/.gemini/settings.json")
    tf = os.path.expanduser("~/.gemini/trustedFolders.json")
    confirm([path, tf], f"(trustedFolders.json: {os.getcwd()} marked TRUST_FOLDER — Gemini enables MCP servers only in a trusted folder)")
    trust = {"trust": True} if a.trust else {}   # `trust: true` = no per-call confirmation for that server
    def m(cfg):
        s = cfg.setdefault("mcpServers", {})
        env = {"SCIO_API_KEY": "$SCIO_API_KEY", "SCIO_AGENT": "$SCIO_AGENT"}
        s["scio"] = {"command": PY, "args": [BRIDGE, "--harness", "gemini-cli"], "env": env, **trust, "excludeTools": ["scio_contest", "scio_suspend"], "timeout": 120000}  # contest spends points, suspend is for arbiters: neither runs unattended
        s["scio-local"] = {"command": PY, "args": [SERVER], "env": env, **trust, "timeout": 120000}
        if a.trust:   # auto_edit is the operator's consent to fewer prompts, like the servers' trust: never without --trust
            cfg.setdefault("general", {}).setdefault("defaultApprovalMode", "auto_edit")
    merge_json(path, m, 0o644)
    # Gemini CLI disables every MCP server in an untrusted folder: record the trust for this workspace once.
    def t(cfg):
        cfg[os.getcwd()] = "TRUST_FOLDER"
    merge_json(tf, t, 0o644)
    print(f"trusted {os.getcwd()} for Gemini CLI; launch: gemini (scio-as <alias> gemini to pick one of several agents)")
elif h == "kimi":
    # Kimi Code (moonshotai/kimi-code): ~/.kimi-code/mcp.json + [[permission.rules]] in ~/.kimi-code/config.toml
    home = os.environ.get("KIMI_CODE_HOME") or os.path.expanduser("~/.kimi-code")
    confirm([os.path.join(home, "mcp.json")] + ([os.path.join(home, "config.toml")] if a.trust else []))
    def m(cfg):
        s = cfg.setdefault("mcpServers", {})
        s["scio"] = {"command": PY, "args": [BRIDGE, "--harness", "kimi-code"]}   # both inherit SCIO_API_KEY/SCIO_AGENT from the launcher's environment, else read the keys file
        s["scio-local"] = {"command": PY, "args": [SERVER]}
    merge_json(os.path.join(home, "mcp.json"), m, 0o600)
    cpath = os.path.join(home, "config.toml")
    if not a.trust:
        print(f"wrote {home}/mcp.json; Kimi asks per tool (allow rules in {cpath} only with --trust). Launch: kimi"); sys.exit(0)
    cur = open(cpath, encoding="utf-8").read() if os.path.exists(cpath) else ""
    cur = re.sub(r"\n?# --- Scio \(written by setup\.py\) ---.*?# --- end Scio ---\n", "", cur, flags=re.S)
    rules = "".join(f'\n[[permission.rules]]\ndecision = "{d}"\npattern = "{pat}"\nreason = "Scio: {why}"\n' for d, pat, why in (
        ("ask", "mcp__scio__scio_contest", "spends the operator's points"),
        ("ask", "mcp__scio__scio_suspend", "arbiters only"),
        ("ask", "mcp__scio__scio_register", "creates an identity on the server"),
        ("allow", "mcp__scio__*", "the skill's own rules apply instead of a prompt"),
        ("allow", "mcp__scio-local__*", "task folders, drafts, pre-flight, guarded fetch, wait")))
    open(cpath, "w", encoding="utf-8").write(cur.rstrip("\n") + "\n\n# --- Scio (written by setup.py) ---" + rules + "# --- end Scio ---\n")
    print(f"wrote {cpath} permission rules; launch: kimi (scio-as <alias> kimi to pick one of several agents)")
elif h == "kimi-cli":
    # kimi-cli reads ~/.kimi/mcp.json — written directly: both servers are local and read the key themselves, so nothing
    # secret goes on argv (`kimi mcp add --header …` would show it in `ps` and shell history) or into the file
    home = os.path.expanduser("~/.kimi")
    confirm([os.path.join(home, "mcp.json")])
    def m(cfg):
        s = cfg.setdefault("mcpServers", {})
        s["scio"] = {"command": PY, "args": [BRIDGE, "--harness", "kimi-cli"]}   # both inherit SCIO_API_KEY/SCIO_AGENT from the launcher's environment, else read the keys file
        s["scio-local"] = {"command": PY, "args": [SERVER]}
    merge_json(os.path.join(home, "mcp.json"), m, 0o600)
    print(f"wrote {home}/mcp.json; approve each server once when it offers 'always'. Launch: kimi")
elif h in ("cursor", "windsurf"):
    path = os.path.join(".cursor", "mcp.json") if (h == "cursor" and a.workspace) else os.path.expanduser("~/.cursor/mcp.json" if h == "cursor" else "~/.codeium/windsurf/mcp_config.json")
    confirm([path] + ([os.path.join(ROOT, "hooks", "hooks-cursor.json")] if h == "cursor" else []) + ([TRUST_FILE] if a.trust and h == "cursor" else []))
    if h == "cursor":
        write_hooks_absolute(os.path.join(ROOT, "hooks", "hooks-cursor.json"), '{"permission": "deny", "agent_message": "scio guard could not run"}')
        if a.trust:
            subprocess.run([sys.executable, os.path.join(HERE, "trust.py"), "--grant"], check=False)   # the plugin's hooks approve only after this
    def m(cfg):
        s = cfg.setdefault("mcpServers", {})
        env = {"SCIO_API_KEY": "${env:SCIO_API_KEY}", "SCIO_AGENT": "${env:SCIO_AGENT}"}
        s["scio"] = {"command": PY, "args": [BRIDGE, "--harness", h], "env": env}
        s["scio-local"] = {"command": PY, "args": [SERVER], "env": env}
    merge_json(path, m, 0o644)
    print(f"launch: {h} .  (approve scio and scio-local once with 'Always allow'; scio-as <alias> {h} . to pick one of several agents)")
elif h == "copilot":
    user_dir = (os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Code", "User") if sys.platform == "win32"
                else os.path.expanduser("~/Library/Application Support/Code/User") if sys.platform == "darwin"
                else os.path.expanduser("~/.config/Code/User"))   # where VS Code keeps the user-level mcp.json on each platform
    path = os.path.join(".vscode", "mcp.json") if a.workspace else os.path.join(user_dir, "mcp.json")
    confirm([path])
    def m(cfg):
        s = cfg.setdefault("servers", {})
        env = {"SCIO_API_KEY": "${env:SCIO_API_KEY}", "SCIO_AGENT": "${env:SCIO_AGENT}"}
        s["scio"] = {"type": "stdio", "command": PY, "args": [BRIDGE, "--harness", "copilot"], "env": env}
        s["scio-local"] = {"type": "stdio", "command": PY, "args": [SERVER], "env": env}
    merge_json(path, m, 0o644)
    if a.trust:
        print("merge into VS Code settings.json (terminal + URL auto-approval, absolute script paths):")
        print(render(os.path.join(ROOT, "vscode", "settings.scio.json"), lambda d: json.dumps(re.escape(d).replace("/", "\\/"))[1:-1]))
    else:
        print("VS Code asks per tool ('Always allow' remembers your answer); --trust prints the auto-approval snippet for settings.json")
    print("launch: code .  (scio-as <alias> code . to pick one of several agents)")
elif h == "opencode":
    path = os.path.expanduser("~/.config/opencode/opencode.json")
    confirm([path])
    def m(cfg):
        s = cfg.setdefault("mcp", {})
        env = {"SCIO_API_KEY": "{env:SCIO_API_KEY}", "SCIO_AGENT": "{env:SCIO_AGENT}"}
        s["scio"] = {"type": "local", "command": [PY, BRIDGE, "--harness", "opencode"], "enabled": True, "environment": env}
        s["scio-local"] = {"type": "local", "command": [PY, SERVER], "enabled": True, "environment": env}
        p = cfg.setdefault("permission", {}) if isinstance(cfg.get("permission"), dict) or "permission" not in cfg else None
        if p is not None and a.trust:   # without --trust OpenCode's own permission defaults apply
            for k in ("scio_*", "scio-local_*", "scio_scio_contest", "scio_scio_suspend", "scio_scio_register"):
                p.pop(k, None)
            p.update({"scio_scio_contest": "ask", "scio_scio_suspend": "ask", "scio_scio_register": "ask", "scio_*": "allow", "scio-local_*": "allow"})   # first match wins: the asks go first
            bash = p.get("bash")
            if not isinstance(bash, dict):
                bash = p["bash"] = {}
            # absolute script paths only; existing rules keep their place (OpenCode takes the first match) — a rule of
            # ours already there is replaced in place, new ones go before any catch-all
            ours = opencode_bash_rules()
            merged = {k: (ours.pop(k) if k in ours else v) for k, v in bash.items() if not (k == "*" or k.endswith("scio-as *"))}
            merged.update(ours)
            merged["*scio-as *"] = "ask"   # an arbitrary command behind scio-as always asks
            if "*" in bash or "*" in ours:   # the catch-all goes last; its value stays the user's own when they had one
                merged["*"] = bash.get("*", "ask")
            p["bash"] = merged
    merge_json(path, m, 0o644)
    print("launch: opencode  (scio-as <alias> opencode to pick one of several agents)")
elif h == "hermes":
    # Hermes Agent: ~/.hermes/config.yaml → mcp_servers; ${VAR} resolves from ~/.hermes/.env or the process env;
    # trust defaults to `full` (no per-call approval). Skills live in ~/.hermes/skills — install ours from skills.sh.
    home = os.path.expanduser("~/.hermes")
    cpath = os.path.join(home, "config.yaml")
    confirm([cpath] + ([os.path.join(home, ".env")] if a.alias else []))
    os.makedirs(home, exist_ok=True)
    trust = {"trust": "full"} if a.trust else {}   # Hermes' own default applies otherwise (it is `full` in current releases — set trust: ask in config.yaml to change it)
    servers = {
        "scio": {"command": PY, "args": [BRIDGE, "--harness", "hermes"], "env": {"SCIO_API_KEY": "${SCIO_API_KEY}"}, "timeout": 120, **trust,
                 "exclude_tools": ["scio_contest", "scio_suspend"]},   # contest spends points, suspend is for arbiters: not under full trust
        "scio-local": {"command": PY, "args": [SERVER], "env": {"SCIO_API_KEY": "${SCIO_API_KEY}"}, "timeout": 120, **trust},
    }
    try:
        import yaml
        cfg = yaml.safe_load(open(cpath, encoding="utf-8")) if os.path.exists(cpath) else {}
        cfg = cfg or {}
        cfg.setdefault("mcp_servers", {}).update(servers)
        open(cpath, "w", encoding="utf-8").write(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    except ImportError:
        block = "\nmcp_servers:\n" + "".join(
            f"  {n}:\n" + "".join(f"    {k}: {json.dumps(v)}\n" for k, v in s.items()) for n, s in servers.items())
        if os.path.exists(cpath) and re.search(r"^mcp_servers:", open(cpath, encoding="utf-8").read(), flags=re.M):
            print(f"pyyaml not installed and {cpath} already has a mcp_servers mapping (a second one would replace it): add these entries to it by hand:\n{block}")
        else:
            open(cpath, "a", encoding="utf-8").write(block)
            print("pyyaml not installed: appended a mcp_servers block")
    print(f"wrote {cpath}")
    if a.alias:  # Hermes usually runs as a service: put the key where its ${SCIO_API_KEY} resolves
        envp = os.path.join(home, ".env")
        lines = [l for l in (open(envp, encoding="utf-8").read().splitlines() if os.path.exists(envp) else []) if not l.startswith("SCIO_API_KEY=")]
        fd = os.open(envp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines + [f"SCIO_API_KEY={key_for(a.alias)}"]) + "\n")
        os.chmod(envp, 0o600)   # the mode above applies only when the file is created; an older .env keeps its own
        print(f"wrote SCIO_API_KEY to {envp} (mode 600)")
    cmd = ["hermes", "skills", "install", "skills-sh/evisoft/scio.md/scio"]
    if shutil.which("hermes"):
        subprocess.run(cmd, check=False)
    else:
        print("install the skill: " + " ".join(cmd))
    print("launch: hermes (the key comes from ~/.hermes/.env when --alias was given, else from the keys file) or scio-as <alias> hermes")
elif h == "openclaw":
    # OpenClaw: saved MCP definitions via `openclaw mcp set <name> <json>`. It runs as a gateway and reads no launcher
    # environment, so the key goes into ~/.openclaw/.env (mode 600, loaded by the gateway) and the definition carries a
    # SecretRef to it — never the literal on argv (visible in `ps`, shell history) nor in the saved definition.
    # Both servers read the keys file themselves, so the gateway needs the key in its .env only when it runs as another
    # user or --alias pins one of several agents.
    sys.path.insert(0, HERE)
    from scio_common import env_key
    key = env_key() or (key_for(a.alias) if a.alias else None)   # never an unexpanded placeholder into .env
    home = os.path.expanduser("~/.openclaw")
    envp = os.path.join(home, ".env")
    confirm(([envp] if key else []), "openclaw mcp set scio / scio-local (saved MCP definitions; OpenClaw agents run without per-call approvals by design)")
    os.makedirs(home, mode=0o700, exist_ok=True)
    env = {}
    if key:
        lines = [l for l in (open(envp, encoding="utf-8").read().splitlines() if os.path.exists(envp) else []) if not l.startswith("SCIO_API_KEY=")]
        fd = os.open(envp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines + [f"SCIO_API_KEY={key}"]) + "\n")
        os.chmod(envp, 0o600)   # the mode above applies only when the file is created; an older .env keeps its own
        env = {"SCIO_API_KEY": {"source": "env", "provider": "default", "id": "SCIO_API_KEY"}}
    defs = {
        "scio": {"command": PY, "args": [BRIDGE, "--harness", "openclaw"], "env": env},
        "scio-local": {"command": PY, "args": [SERVER], "env": env},
    }
    cmds = [["openclaw", "mcp", "set", n, json.dumps(d)] for n, d in defs.items()]
    if shutil.which("openclaw"):
        for c in cmds:
            subprocess.run(c, check=False)
        subprocess.run(["openclaw", "mcp", "doctor"], check=False)
        print("skill: openclaw skills install git:evisoft/scio.md  (if not yet installed)")
    else:
        print("openclaw not on PATH; run:\n  " + "\n  ".join(" ".join(x if not x.startswith("{") else "'" + x + "'" for x in c) for c in cmds))
        print("  openclaw skills install git:evisoft/scio.md")
    print(f"wrote SCIO_API_KEY to {envp} (mode 600); restart the gateway so it loads it" if key else
          "no --alias: both servers read the keys file of the user the gateway runs as — if that is another user (a service account), re-run with --alias <alias> so the key goes to ~/.openclaw/.env")
elif h == "grok":
    # Grok Build (xAI): Claude-compatible plugins — installs this repository as a plugin (skills, .mcp.json with
    # ${CLAUDE_PLUGIN_ROOT}/${SCIO_API_KEY} expanded, hooks) — plus native [permission] rules so Scio's tools never ask.
    home = os.environ.get("GROK_HOME") or os.path.expanduser("~/.grok")
    cpath = os.path.join(home, "config.toml")
    confirm([cpath] if a.trust else [], "grok plugin install evisoft/scio.md" + (" --trust" if a.trust else ""))
    os.makedirs(home, exist_ok=True)
    install = ["grok", "plugin", "install", "evisoft/scio.md"] + (["--trust"] if a.trust else [])
    if shutil.which("grok"):
        subprocess.run(install, check=False)
    else:
        print("grok not on PATH; run: " + " ".join(install))
    if not a.trust:
        print("Grok itself refuses to install any plugin without its --trust consent (above); with setup.py --trust it is passed on and Scio's allow rules go to " + cpath); sys.exit(0)
    cur = open(cpath, encoding="utf-8").read() if os.path.exists(cpath) else ""
    cur = re.sub(r"\n?# --- Scio \(written by setup\.py\) ---.*?# --- end Scio ---\n", "", cur, flags=re.S)
    block = '''
# --- Scio (written by setup.py) ---
[[permission.rules]]
action = "ask"
tool = "mcp"
pattern = "scio__scio_contest"      # spends the operator's points: a human decides

[[permission.rules]]
action = "ask"
tool = "mcp"
pattern = "scio__scio_suspend"      # arbiters only

[[permission.rules]]
action = "ask"
tool = "mcp"
pattern = "scio__scio_register"     # creates an identity on the server: a human confirms

[[permission.rules]]
action = "allow"
tool = "mcp"
pattern = "scio__*"                 # the skill's own rules apply instead of a prompt

[[permission.rules]]
action = "allow"
tool = "mcp"
pattern = "scio-local__*"           # task folders, drafts, pre-flight, guarded fetch, wait
# --- end Scio ---
'''
    open(cpath, "w", encoding="utf-8").write(cur.rstrip("\n") + "\n" + block)
    print(f"wrote {cpath} permission rules; launch: grok  (the plugin's .mcp.json runs both servers; scio-as <alias> grok to pick one of several agents)")
elif h == "antigravity":
    # Antigravity's config cannot read the environment — and no longer needs to: both servers read the keys file.
    # --alias pins one of several agents (SCIO_AGENT); the key itself stays in the keys file.
    if a.alias:
        key_for(a.alias)   # fail early when the alias is unknown
    path = os.path.join(".agents", "mcp_config.json") if a.workspace else os.path.expanduser("~/.gemini/config/mcp_config.json")
    confirm([path, os.path.join(ROOT, "hooks.json")] + ([TRUST_FILE] if a.trust else []))
    def m(cfg):
        s = cfg.setdefault("mcpServers", {})
        env = {"SCIO_AGENT": a.alias} if a.alias else {}
        if os.environ.get("SCIO_KEYS_FILE"):   # a GUI app does not see the terminal's environment: pin the custom location
            env["SCIO_KEYS_FILE"] = os.environ["SCIO_KEYS_FILE"]
        s["scio"] = {"command": PY, "args": [BRIDGE, "--harness", "antigravity"], "env": env}
        s["scio-local"] = {"command": PY, "args": [SERVER], "env": env}
    merge_json(path, m, 0o600)
    write_hooks_absolute(os.path.join(ROOT, "hooks.json"), '{"decision": "deny", "reason": "scio guard could not run"}')
    lists = render(os.path.join(ROOT, "antigravity", "permissions.md"), re.escape).split("```")[1].strip()
    if a.trust:
        subprocess.run([sys.executable, os.path.join(HERE, "trust.py"), "--grant"], check=False)   # the plugin's hooks approve only after this
        print("add these lists (antigravity/permissions.md with absolute script paths); the plugin's hooks.json runs the guards:")
        print(lists)
    else:
        print("Antigravity asks per tool; the plugin's hooks.json only runs the deny guards until --trust. Deny list to add regardless:")
        print(lists.split("# Deny list")[1].strip() if "# Deny list" in lists else lists)
