#!/usr/bin/env bash
# Cut a release: scripts/release.sh 0.3.0
# Policy: a release at every version bump — including every contract change from evisoft/scio (regenerated tools.md
# counts) — and v1.0.0 only when the platform leaves alpha. Steps: versions in sync, tools.md current, stats line,
# security suite, manifest LAST, tag, GitHub release with generated notes.
set -euo pipefail
v="${1:?usage: release.sh <version, e.g. 0.3.0>}"
cd "$(dirname "$0")/.."
sed -i "s/\"version\": \"[0-9.]*\"/\"version\": \"$v\"/" .claude-plugin/plugin.json .claude-plugin/marketplace.json gemini-extension.json .cursor-plugin/plugin.json plugin.json .cursor-plugin/marketplace.json
sed -i "s/^  version: \"[0-9.]*\"/  version: \"$v\"/" skills/scio/SKILL.md openclaw/scio/SKILL.md
if [ -f ../scio/contracts/tools.json ]; then python3 scripts/gen-tools-md.py ../scio/contracts/tools.json > skills/scio/references/tools.md; python3 scripts/gen-tools-list.py ../scio/contracts/tools.json > skills/scio/server/tools.json; fi
python3 scripts/gen-stats-line.py || true
python3 skills/scio/scripts/refresh-rules.py   # the bundled rules mirror comes only from the verified signed document
python3 tests/test-security.py >/dev/null
python3 scripts/gen-manifest.py
(cd skills/scio && sha256sum -c MANIFEST.sha256 --quiet)
manifest_sha=$(sha256sum skills/scio/MANIFEST.sha256 | cut -d' ' -f1)   # goes into the release notes: the end of the end-to-end check (security.md §2.8)
claude plugin validate . >/dev/null
git add -A
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
# plugin.json and the marketplace entry agree on the version, so it also catches a manifest the sed above missed.
claude plugin tag
git tag -a "v$v" -m "Scio plugin $v"
git push -q
git push -q origin "v$v"
git push -q origin "scio--v$v"
gh release create "v$v" --title "v$v" --notes "MANIFEST.sha256 sha256: $manifest_sha" --generate-notes   # generated notes are appended after --notes
