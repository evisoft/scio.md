#!/usr/bin/env bash
# What one container does: stand up the local wiki, install the skill the way an operator would, wire the
# harness to it, run the checks that need no model, and then — only if a key was passed — give the harness one
# turn and show what it did with it.
#
# Two layers on purpose. The deterministic half decides the exit code; a model's turn is judged by hand,
# because a suite whose verdict depends on what a model chose is a suite that fails one run in five.
set -euo pipefail

HARNESS="${HARNESS:?set HARNESS at build time}"
PORT="${SCIO_FAKE_PORT:-8787}"
BASE="http://127.0.0.1:${PORT}"
SKILL_SRC=/opt/scio-skill
SKILL="${HOME}/.agents/skills/scio"
PLUGIN="${HOME}/scio-plugin"   # the repository as a plugin, its skill the redirected copy (Claude Code, Grok)

say() { printf '\n=== %s\n' "$*"; }

say "local wiki on ${BASE}"
python3 /repo/tests/fake_wiki.py --port "${PORT}" >/tmp/wiki.url 2>/tmp/wiki.log &
for _ in $(seq 1 50); do
  curl -fsS "${BASE}/v1/stats" >/dev/null 2>&1 && break
  sleep 0.2
done
curl -fsS "${BASE}/v1/stats" | head -c 200; echo
sed -n '1p' /tmp/wiki.log || true

say "the skill, redirected at it"
# The installed tree has no variable that moves the bearer's destination; a rewritten copy is the only way in.
python3 /repo/tests/fake_wiki.py --skill-copy "${SKILL_SRC}" --base-url "${BASE}" >/dev/null
mkdir -p "$(dirname "${SKILL}")"
rm -rf "${SKILL}"
cp -a "${SKILL_SRC}" "${SKILL}"
grep -c "${BASE}" "${SKILL}/scripts/scio_common.py" >/dev/null && echo "  copy aimed at ${BASE}"

# Claude Code and Grok load a plugin, not a skill folder: the plugin under test is this repository with the
# redirected skill in it. Neither may fall back on the published plugin — that one talks to scio.md, which this
# container maps to 127.0.0.1, so the harness's turn would reach nothing and the run would still say ok.
mkdir -p "${PLUGIN}/skills"
cp -a /repo/.claude-plugin /repo/.mcp.json /repo/hooks /repo/commands /repo/agents "${PLUGIN}/"
rm -rf "${PLUGIN}/skills/scio"
cp -a "${SKILL_SRC}" "${PLUGIN}/skills/scio"

say "wiring ${HARNESS}"
case "${HARNESS}" in
  claude)   # loaded per session with --plugin-dir (below); setup.py only records the trust grant
    python3 "${SKILL}/scripts/setup.py" --harness claude --yes --trust 2>&1 | tail -3
    WIRED=(--plugin "${PLUGIN}") ;;
  grok)     # installed from its local path; setup.py would install evisoft/scio.md from GitHub, so it runs with grok
            # off its PATH and writes only the permission rules
    grok plugin install "${PLUGIN}" --trust 2>&1 | tail -3
    PATH="$(printf '%s' "${PATH}" | tr ':' '\n' | grep -v '/\.grok/' | paste -sd: -)" \
      python3 "${PLUGIN}/skills/scio/scripts/setup.py" --harness grok --yes --trust 2>&1 | tail -3
    WIRED=() ;;
  *)
    python3 "${SKILL}/scripts/setup.py" --harness "${HARNESS}" --yes --trust 2>&1 | tail -3
    WIRED=() ;;
esac

say "deterministic checks"
# `|| status=$?` on purpose: under `set -e` a failing check would abort here, and the sections below are the
# ones that say what the run actually did. Keep its code, keep going, exit with it at the end.
status=0
python3 /repo/tests/sim/wired.py --harness "${HARNESS}" --home "${HOME}" --base-url "${BASE}" ${WIRED[@]+"${WIRED[@]}"} || status=$?
python3 /repo/tests/sim/check.py --skill "${SKILL}" --base-url "${BASE}" --harness "${HARNESS}" || status=$?

say "the harness's own turn"
PROMPT="${SCIO_SIM_PROMPT:-Call the scio_whoami tool and tell me the rank it reports. Do nothing else.}"
case "${HARNESS}" in
  claude) CMD=(claude --plugin-dir "${PLUGIN}" -p "${PROMPT}") ;;
  codex)  CMD=(codex exec "${PROMPT}") ;;
  gemini) CMD=(gemini -p "${PROMPT}") ;;
  grok)   CMD=(grok -p "${PROMPT}") ;;
  kimi)   CMD=(kimi -p "${PROMPT}") ;;
esac
if [ -n "${SCIO_SIM_MODEL_KEY:-}" ]; then
  echo "  ${CMD[0]} with a model key present"
  timeout "${SCIO_SIM_TIMEOUT:-300}" "${CMD[@]}" 2>&1 | tail -30 || echo "  (the harness exited non-zero; read the turn above)"
else
  echo "  skipped: no model key passed. The checks above already ran without one."
  echo "  would run: ${CMD[*]}"
fi

say "what the wiki saw"
curl -fsS "${BASE}/v1/stats" | head -c 300; echo
exit "${status}"
