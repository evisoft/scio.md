# One image per harness, same file: `--build-arg HARNESS=claude|codex|gemini|grok|kimi`.
#
# The image never carries a model key. `tests/sim/simulate.sh` passes the one the chosen harness wants at run
# time, and the run works without any of them — everything except the harness's own turn is deterministic.
#
# SCIO_SIMULATION=1 is set here on purpose. It arms the seatbelt in scio_common.live_registration_refused(), so
# if the redirected skill copy is ever missing or wrong, the run refuses to register rather than adding an agent
# to the real wiki. simulate.sh also points scio.md at 127.0.0.1 inside the container, so a request that somehow
# escaped the copy fails instead of arriving.
FROM node:22-slim

ARG HARNESS
# /root/.local/bin has to be on PATH *before* the install step: kimi's script installs uv there and then looks
# for it, and fails with "uv not found after installation" if the shell cannot see it yet.
ENV HARNESS=${HARNESS} \
    SCIO_SIMULATION=1 \
    SCIO_NUDGE=off \
    PATH="/root/.local/bin:/root/.grok/bin:/usr/local/bin:${PATH}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/*

# Each harness installs its own way; the two that are not on npm publish a script, whose URL is in their own
# binaries. Both scripts are bash, and this image's /bin/sh is dash — piping them to `sh` dies on a syntax error.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN set -eux; \
    case "${HARNESS}" in \
      claude) npm install -g @anthropic-ai/claude-code ;; \
      codex)  npm install -g @openai/codex ;; \
      gemini) npm install -g @google/gemini-cli ;; \
      grok)   curl -fsSL https://x.ai/cli/install.sh | bash ;; \
      kimi)   curl -fsSL https://code.kimi.com/install.sh | bash ;; \
      *) echo "HARNESS must be one of claude codex gemini grok kimi (got '${HARNESS}')" >&2; exit 2 ;; \
    esac; \
    command -v "${HARNESS}" >/dev/null || { echo "${HARNESS} is not on PATH after installing it" >&2; exit 3; }

# What the simulation reads, and nothing else: the skill, the tests with the stand-in, and the plugin files a
# harness loads (the plugin under test is built from them in run.sh). Never `COPY .` — a maintainer's .env, the
# usual home of the model keys simulate.sh passes at run time, would be baked into a layer of every image.
WORKDIR /repo
COPY skills /repo/skills
COPY tests /repo/tests
COPY scripts /repo/scripts
COPY .claude-plugin /repo/.claude-plugin
COPY .mcp.json /repo/.mcp.json
COPY hooks /repo/hooks
COPY commands /repo/commands
COPY agents /repo/agents

ENTRYPOINT ["/repo/tests/sim/run.sh"]
