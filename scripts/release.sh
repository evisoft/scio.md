#!/usr/bin/env bash
# Cut a release: scripts/release.sh 0.3.0 [<contract>]
# <contract> is the platform's tool contract: a path, or by default https://scio.md/v1/tools.json — the one deployed.
# Policy: a release at every version bump — including every contract change from evisoft/scio (regenerated tools.md
# counts) — and v1.0.0 only when the platform leaves alpha. Steps: a clean tree, versions in sync, the contract's three
# copies from one source, stats line, rules, security suite, manifests LAST, tag, GitHub release with generated notes.
# Portable: bash, git and python3 do the work — no `sed -i` (BSD and GNU disagree on it), no sha256sum (not on macOS).
set -euo pipefail
v="${1:?usage: release.sh <version, e.g. 0.3.0> [<contract path, or https://scio.md/v1/tools.json by default>]}"
contract="${2:-https://scio.md/v1/tools.json}"
cd "$(dirname "$0")/.."
# The release commit holds what this script rewrites and nothing else: an experiment lying in the checkout (untracked
# files included) would otherwise ship inside a tag the ruleset makes immutable.
dirty="$(git status --porcelain --untracked-files=all)"
if [ -n "$dirty" ]; then
    printf 'release.sh: the working tree is not clean; commit or remove these first:\n%s\n' "$dirty" >&2
    exit 1
fi
python3 scripts/bump-version.py "$v"
python3 scripts/sync-contract.py "$contract"   # tools.md, server/tools.json and the stand-in's snapshot; fails when there is no contract
python3 scripts/gen-stats-line.py || true
python3 skills/scio/scripts/refresh-rules.py   # the bundled rules mirror comes only from the verified signed document
# The manifests LAST among the edits, and before the suite: the suite checks that they match the tree, and every step
# above rewrote files they hash (versions, the contract copies, the rules, the README badges). The suite edits nothing.
python3 scripts/gen-manifest.py             # the skill's manifest and the plugin root's
# The suite's output is kept, not thrown away: a failure says which check failed, and a hang shows where it stopped.
if ! suite="$(python3 tests/test-security.py 2>&1)"; then
    printf '%s\n' "$suite" | grep -E '^ +FAIL|Traceback|Error' >&2 || true
    printf '%s\n' "$suite" | tail -n 30 >&2
    echo "release.sh: the security suite failed (above: what failed, then the end of its output)" >&2
    exit 1
fi
printf '%s\n' "$suite" | tail -n 1
python3 scripts/gen-manifest.py --check     # every listed hash verified against the tree, after the suite too
notes="$(python3 scripts/gen-manifest.py --notes)"   # goes into the release notes: the end of the end-to-end check (security.md §2.8)
claude plugin validate . >/dev/null
# Stage exactly what the steps above rewrite; anything else they changed stops the release instead of riding along.
git add -- .claude-plugin/plugin.json .claude-plugin/marketplace.json .cursor-plugin/plugin.json .cursor-plugin/marketplace.json \
    plugin.json gemini-extension.json skills/scio/SKILL.md openclaw/scio/SKILL.md \
    skills/scio/references/tools.md skills/scio/server/tools.json tests/wiki/tools.json \
    skills/scio/references/rules.md skills/scio/references/roles.md skills/scio/scripts/whoami.py \
    README*.md skills/scio/MANIFEST.sha256 PLUGIN.sha256
left="$(git status --porcelain --untracked-files=all | grep -Ev '^[MADRC] ' || true)"
if [ -n "$left" ]; then
    printf 'release.sh: these changed during the release but are not among the files it commits:\n%s\n' "$left" >&2
    exit 1
fi
if git diff --cached --quiet; then
    echo "Release files already committed."
else
    diff_status=$?
    [ "$diff_status" -eq 1 ] || exit "$diff_status"
    git commit -q -m "Release v$v"
fi
# Two tag series, on purpose. v$v is the release, and the ruleset makes it immutable. scio--v$v is what dependency
# resolution looks for ({plugin-name}--v{version}, docs/en/plugin-dependencies): without it a plugin that constrained
# scio to a range would fail with no-matching-tag. `claude plugin tag` derives the name itself and refuses unless
# plugin.json and the marketplace entry agree on the version, so it also catches a manifest bump-version.py missed.
claude plugin tag
git tag -a "v$v" -m "Scio plugin $v"
git push -q
git push -q origin "v$v"
git push -q origin "scio--v$v"
gh release create "v$v" --title "v$v" --notes "$notes" --generate-notes   # generated notes are appended after --notes
