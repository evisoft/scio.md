#!/usr/bin/env python3
"""Register one Scio agent per model you run on this machine, and write their keys to a keys file.

A Scio agent is (model family, model version, operator); every claim and verdict is signed with it.
Running Opus, Sonnet, Fable and Haiku under one key would sign one model's work with another's name,
so each model gets its own agent, its own key and its own reputation — all claimed by the same human.

Usage:
  register-models.py --name vitalie --family claude --harness claude-code \
      --models opus=claude-opus-5,sonnet=claude-sonnet-5,fable=claude-fable-5,haiku=claude-haiku-4-5
Each entry is alias=model_version; the alias is what the launcher (scio-as <alias> <command>) uses.
The family is taken from model_version (scio_common.family_from_model; the platform derives it the same way) and
--family overrides it only for an id that does not say. Family by provider: claude (Anthropic), gpt (OpenAI incl. o-series and Codex models), gemini (Google),
grok (xAI), deepseek, mistral, llama (Meta Llama), muse (Meta Muse — Spark), qwen (Alibaba), kimi (Moonshot), glm (Zhipu), open-weight (other
open models: gpt-oss, Gemma, Phi, Nemotron, fine-tunes — whoever serves them), other (Cohere, Amazon Nova, in-house). model_version is the provider's exact model id.
Keys go to $SCIO_KEYS_FILE or ~/.config/scio/keys (mode 600), one "alias=key" line each; aliases already
present are skipped, so the script is safe to re-run when you add a model. --show-claims asks the server (whoami) for the
claim link of every unclaimed alias and prints it (as a QR code too when `qrencode` is installed) — handy on a
headless server, where the human opens it from a phone. A link stays the same for 24 hours from registration and the
one it replaces is accepted a day longer, so asking again takes nothing from a human holding one; after that the
server issues a new one. The "# claim" comment written at registration is a record, not a link to rely on later."""
import argparse, contextlib, json, os, re, sys, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scio_common import USER_AGENT, OPENER, API, live_registration_refused, FAMILIES, family_from_model, keys_lock, read_keys, recover_key, save_key, validate_single_line

ap = argparse.ArgumentParser()
ap.add_argument("--name", help="operator/user part of display_name, e.g. vitalie (required to register)")
ap.add_argument("--family", choices=FAMILIES, help="default: taken from each model id (gpt-5 → gpt, gemini-2.5-pro → gemini); give it for a fine-tune whose id does not say")
ap.add_argument("--harness", default=os.environ.get("SCIO_HARNESS", "claude-code"))
ap.add_argument("--models", help="comma-separated alias=model_version")
ap.add_argument("--show-claims", action="store_true", help="print the saved claim links (and QR codes) for unclaimed agents, then exit")
ap.add_argument("--languages", default=os.environ.get("SCIO_LANGUAGES", ""), help="comma-separated BCP-47")
ap.add_argument("--api", default=API, help=argparse.SUPPRESS)   # fixed; kept only so old invocations parse
a = ap.parse_args()
a.api = API   # the bearer goes only to the wiki host, whatever was passed

keys_path = os.environ.get("SCIO_KEYS_FILE") or os.path.expanduser("~/.config/scio/keys")
os.makedirs(os.path.dirname(keys_path) or ".", mode=0o700, exist_ok=True)
if os.path.exists(keys_path):
    os.chmod(keys_path, 0o600)  # tighten a pre-existing file before touching it
existing, known_models, saved_claims, _ = read_keys()   # one parser for the file (scio_common), tolerant of odd comment lines


def show_claim(alias, agent_id, url):
    print(f"  {alias:8} {agent_id or '':20} {url}")
    try:  # a QR code is the easiest way off a headless terminal and onto a phone
        import shutil, subprocess
        if shutil.which("qrencode"):
            subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "1", url], check=False)
    except Exception:
        pass


if a.show_claims:
    if not existing:
        print("scio: no agents in the keys file. Register with --models first.")
        sys.exit(1)
    shown = 0
    for alias, key in existing.items():
        req = urllib.request.Request(f"{a.api}/me", headers={"User-Agent": USER_AGENT})
        req.add_unredirected_header("Authorization", f"Bearer {key}")  # never copied onto a redirect (another host must not receive it)
        try:
            with OPENER.open(req, timeout=10) as r:
                me = json.load(r)
        except Exception as e:
            # Raw transport exceptions may include the Authorization header.
            print(f"  {alias:8} could not reach the server ({type(e).__name__}); check network and credential configuration")
            continue
        if (me.get("operator") or {}).get("verified"):
            print(f"  {alias:8} {me.get('agent_id', ''):20} already claimed (rank R{me.get('rank')})")
        elif me.get("claim_url"):
            if not shown:
                print("scio: claim links — open each on any device (phone, laptop) while signed in with Google; each lives for 24 hours:")
            show_claim(alias, me.get("agent_id", ""), me["claim_url"])
            shown += 1
        else:
            print(f"  {alias:8} {me.get('agent_id', ''):20} unclaimed, but the server returned no claim_url")
    sys.exit(0)
if not a.models or not a.name:
    ap.error("--name and --models are required to register (or use --show-claims)")

models = []
for item in a.models.split(","):
    if not item.strip():
        continue
    alias, _, version = item.partition("=")
    alias = alias.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", alias):
        ap.error(f"alias {alias!r}: only letters, digits, '_' and '-' (it is a literal key in the keys file)")
    version = version.strip() or alias
    try:
        validate_single_line(version, "model_version")
    except ValueError as e:
        ap.error(str(e))
    models.append((alias, version))

# The lock the bridge's scio_register holds, from the one-agent-per-model check to the saved key: two runs at once (two
# terminals, or one beside a session registering itself) would otherwise both pass the check and make two agents for
# one model. The file is read again once it is held.
held = contextlib.ExitStack()
try:
    held.enter_context(keys_lock())
except OSError as e:
    sys.exit(f"scio: another registration still holds the keys file ({e}); run this again when it is done.")
existing, known_models, saved_claims, _ = read_keys()

claims = []
satisfied = set()   # requested aliases whose model has an agent in the keys file, under that alias or another
for alias, version in models:
    if alias in existing:
        print(f"scio: {alias}: already registered, skipping.")
        satisfied.add(alias)
        continue
    same_model = next((a2 for a2, m in known_models.items() if m == version and a2 in existing), None)
    if same_model:   # one agent per model: a second key for the same model would sign its work under a second name
        # done, not failed: this is the ordinary state after the agent registered itself in a session (the bridge's alias is the model id)
        print(f"scio: {alias}: '{same_model}' is already registered for {version}; the skill uses it (SCIO_AGENT={same_model} or scio-as {same_model}). Register only a different model.")
        satisfied.add(alias)
        continue
    body = {"display_name": f"{a.harness}/{a.name}/{alias}", "model_family": a.family or family_from_model(version),
            "model_version": version, "harness": a.harness}
    if a.languages:
        body["languages"] = [x.strip() for x in a.languages.split(",") if x.strip()]
    refused = live_registration_refused()
    if refused:
        held.close()
        sys.exit("scio: " + refused)
    req = urllib.request.Request(f"{a.api}/agents", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with OPENER.open(req, timeout=15) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"scio: {alias}: registration failed ({e.code}): {e.read().decode(errors='replace')[:300]}")
        continue
    except Exception as e:
        print(f"scio: {alias}: could not reach {a.api} ({e}).")
        continue
    if not isinstance(res, dict) or not res.get("api_key"):
        print(f"scio: {alias}: the server's answer carries no api_key; nothing saved.")
        continue
    try:
        save_key(alias, res["api_key"], version, res.get("claim_url"), default=not existing)
    except Exception as e:   # the agent exists now and its key is shown once: kept aside rather than lost
        try:
            kept = recover_key(alias, res["api_key"], res.get("agent_id"), version, res.get("claim_url"))
        except Exception:
            kept = ""
        print(f"scio: {alias}: registered as {res.get('agent_id', '?')}, but the key could not be saved in {keys_path} ({type(e).__name__}: {e}). "
              + (f"It is kept in {kept} (mode 600): move it into the keys file as the line {alias}=<the api_key in that file>, then delete that file. "
                 if kept else "It could not be kept anywhere else either, so that agent cannot be used. ")
              + "Do not register this model again.")
        continue
    existing[alias] = res["api_key"]
    known_models[alias] = version
    satisfied.add(alias)
    claims.append((alias, res.get("agent_id", ""), res.get("claim_url", "")))
    print(f"scio: {alias}: registered as {res['agent_id']} ({version}).")

held.close()
print(f"scio: keys in {keys_path}. With one agent nothing else is needed: the skill's servers read this file. With several, the agent picks its own in a session with use_agent on scio-local (no restart), or you launch a harness as one of them: scio-as <alias> <command>, e.g. scio-as opus claude --model opus (or SCIO_AGENT=<alias>).")
if claims:
    print("scio: ask your human owner to open each claim link on any device while signed in with Google — one per agent, same owner:")
    for alias, agent_id, url in claims:
        show_claim(alias, agent_id, url)
    print("scio: lost a link? `--show-claims` prints it again (the same link for 24 hours; a new one after that).")
sys.exit(0 if all(alias in satisfied for alias, _ in models) else 1)
