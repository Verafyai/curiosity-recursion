#!/usr/bin/env bash
# Bump the version, append a CHANGELOG entry, commit and tag. Never pushes.
#   scripts/release.sh patch|minor|major "one-line summary"               code release: VERSION, \codeversion and \paperversion
#   scripts/release.sh --paper-only patch|minor|major "one-line summary"  paper revision: only \paperversion, no tag
set -euo pipefail
cd "$(dirname "$0")/.."
PAPER_ONLY=0; if [ "${1:-}" = "--paper-only" ]; then PAPER_ONLY=1; shift; fi
PART=${1:?patch, minor or major}; MSG=${2:?summary}
if [ "$PAPER_ONLY" = 1 ]; then
  CURP=$(sed -n 's/.*\\newcommand{\\paperversion}{\([^}]*\)}.*/\1/p' paper/macros.tex)
  IFS=. read -r MA MI PA <<< "$CURP"
  case $PART in major) MA=$((MA+1)); MI=0; PA=0;; minor) MI=$((MI+1)); PA=0;; patch) PA=$((PA+1));; *) echo "bad part"; exit 2;; esac
  NEWP=$MA.$MI.$PA
  sed -i "s/\\\\newcommand{\\\\paperversion}{[^}]*}/\\\\newcommand{\\\\paperversion}{$NEWP}/" paper/macros.tex
  sed -i "s/badge\/paper-v[0-9.]*-/badge\/paper-v$NEWP-/" README.md 2>/dev/null || true
  { printf '## paper v%s (%s)\n\n- %s (paper only; code stays v%s)\n\n' "$NEWP" "$(date +%F)" "$MSG" "$(cat VERSION)"; cat CHANGELOG.md 2>/dev/null | sed '1{/^# Changelog/d}'; } > CHANGELOG.tmp
  { echo "# Changelog"; echo; cat CHANGELOG.tmp; } > CHANGELOG.md; rm CHANGELOG.tmp
  git add -A CHANGELOG.md README.md paper
  git commit -m "Paper v$NEWP: $MSG (paper only)"
  echo "paper v$NEWP committed (no tag, not pushed)"
  exit 0
fi
CUR=$(cat VERSION 2>/dev/null || echo 0.0.0)
IFS=. read -r MA MI PA <<< "$CUR"
case $PART in major) MA=$((MA+1)); MI=0; PA=0;; minor) MI=$((MI+1)); PA=0;; patch) PA=$((PA+1));; *) echo "bad part"; exit 2;; esac
NEW=$MA.$MI.$PA
echo "$NEW" > VERSION
sed -i "s/^version: .*/version: $NEW/; s/^date-released: .*/date-released: $(date +%F)/" CITATION.cff 2>/dev/null || true
sed -i "s/\\\\newcommand{\\\\paperversion}{[^}]*}/\\\\newcommand{\\\\paperversion}{$NEW}/" paper/macros.tex 2>/dev/null || true
sed -i "s/\\\\newcommand{\\\\codeversion}{[^}]*}/\\\\newcommand{\\\\codeversion}{$NEW}/" paper/macros.tex 2>/dev/null || true
sed -i "s/badge\/version-v[0-9.]*-/badge\/version-v$NEW-/; s/badge\/paper-v[0-9.]*-/badge\/paper-v$NEW-/" README.md 2>/dev/null || true
KEYV=$(ls eval/answer_keys | sort -V | tail -1)
{ printf '## v%s (%s)\n\n- %s\n- Answer key: %s\n- Leaderboard: benchmark/BENCHMARK.md\n\n' "$NEW" "$(date +%F)" "$MSG" "$KEYV"; cat CHANGELOG.md 2>/dev/null | sed '1{/^# Changelog/d}'; } > CHANGELOG.tmp
{ echo "# Changelog"; echo; cat CHANGELOG.tmp; } > CHANGELOG.md; rm CHANGELOG.tmp
git add -A VERSION CHANGELOG.md CITATION.cff benchmark paper eval/answer_keys
git commit -m "Release v$NEW: $MSG"
git tag -a "v$NEW" -m "v$NEW: $MSG"
echo "tagged v$NEW (not pushed; push with: git push origin HEAD --tags)"
