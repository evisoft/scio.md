#!/usr/bin/env bash
# Build and run one harness simulation, or all five.
#
#   tests/sim/simulate.sh                 every harness, no model keys (deterministic half only)
#   tests/sim/simulate.sh claude codex    just these
#   ANTHROPIC_API_KEY=… tests/sim/simulate.sh claude    …and give Claude Code a turn
#
# The key for the chosen harness is passed through at run time and never reaches the image. scio.md is pointed
# at 127.0.0.1 inside the container, so a request that escaped the redirected skill copy fails instead of
# arriving at the real wiki — belt to the seatbelt SCIO_SIMULATION already provides.
set -euo pipefail
cd "$(dirname "$0")/../.."

ALL=(claude codex gemini grok kimi)
WANTED=("${@:-${ALL[@]}}")

key_var() {
  case "$1" in
    claude) echo ANTHROPIC_API_KEY ;;
    codex)  echo OPENAI_API_KEY ;;
    gemini) echo GEMINI_API_KEY ;;
    grok)   echo XAI_API_KEY ;;
    kimi)   echo MOONSHOT_API_KEY ;;
  esac
}

failed=()
for harness in "${WANTED[@]}"; do
  case " ${ALL[*]} " in *" ${harness} "*) ;; *) echo "unknown harness '${harness}' (have: ${ALL[*]})" >&2; exit 2 ;; esac
  printf '\n\n######## %s\n' "${harness}"
  docker build --quiet --build-arg "HARNESS=${harness}" -f tests/sim/Dockerfile -t "scio-sim:${harness}" . >/dev/null

  var="$(key_var "${harness}")"
  run=(docker run --rm --add-host "scio.md:127.0.0.1" -e "SCIO_SIM_TIMEOUT=${SCIO_SIM_TIMEOUT:-300}")
  if [ -n "${!var:-}" ]; then
    run+=(-e "${var}=${!var}" -e "SCIO_SIM_MODEL_KEY=1")
    echo "  ${var} present: the harness gets a turn"
  else
    echo "  ${var} not set: deterministic checks only"
  fi
  "${run[@]}" "scio-sim:${harness}" || failed+=("${harness}")
done

printf '\n\n######## summary\n'
for harness in "${WANTED[@]}"; do
  case " ${failed[*]-} " in *" ${harness} "*) echo "  FAIL ${harness}" ;; *) echo "  ok   ${harness}" ;; esac
done
[ ${#failed[@]} -eq 0 ]
