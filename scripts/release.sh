#!/usr/bin/env bash
# Bump the version, append a CHANGELOG entry, commit and tag. Never pushes.
#   scripts/release.sh patch|minor|major "one-line summary"
set -euo pipefail
cd "$(dirname "$0")/.."
PART=${1:?patch, minor or major}; MSG=${2:?summary}
CUR=$(cat VERSION 2>/dev/null || echo 0.0.0)
IFS=. read -r MA MI PA <<< "$CUR"
case $PART in major) MA=$((MA+1)); MI=0; PA=0;; minor) MI=$((MI+1)); PA=0;; patch) PA=$((PA+1));; *) echo "bad part"; exit 2;; esac
NEW=$MA.$MI.$PA
echo "$NEW" > VERSION
sed -i "s/^version: .*/version: $NEW/; s/^date-released: .*/date-released: $(date +%F)/" CITATION.cff 2>/dev/null || true
sed -i "s/\\\\newcommand{\\\\paperversion}{[^}]*}/\\\\newcommand{\\\\paperversion}{$NEW}/" paper/macros.tex 2>/dev/null || true
sed -i "s/badge\/version-v[0-9.]*-/badge\/version-v$NEW-/; s/badge\/paper-v[0-9.]*-/badge\/paper-v$NEW-/" README.md 2>/dev/null || true
KEYV=$(ls eval/answer_keys | sort -V | tail -1)
{ printf '## v%s (%s)\n\n- %s\n- Answer key: %s\n- Leaderboard: benchmark/BENCHMARK.md\n\n' "$NEW" "$(date +%F)" "$MSG" "$KEYV"; cat CHANGELOG.md 2>/dev/null | sed '1{/^# Changelog/d}'; } > CHANGELOG.tmp
{ echo "# Changelog"; echo; cat CHANGELOG.tmp; } > CHANGELOG.md; rm CHANGELOG.tmp
git add -A VERSION CHANGELOG.md CITATION.cff benchmark paper eval/answer_keys
git commit -m "Release v$NEW: $MSG"
git tag -a "v$NEW" -m "v$NEW: $MSG"
echo "tagged v$NEW (not pushed; push with: git push origin HEAD --tags)"
