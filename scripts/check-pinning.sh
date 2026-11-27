#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
fail=0

if [ -d .github/workflows ]; then
  while IFS= read -r hit; do
    echo "::error::Action nicht per Commit-SHA gepinnt: $hit"
    fail=1
  done < <(grep -rnE '^[[:space:]-]*uses:' .github/workflows \
             | grep -vE 'uses:[[:space:]]*["'\'']?\./' \
             | grep -vE '@[0-9a-f]{40}([[:space:]"'\'']|$)' || true)
fi

while IFS= read -r -d '' file; do
  while IFS= read -r hit; do
    echo "::error::Image nicht per Digest gepinnt: $file:$hit"
    fail=1
  done < <(grep -niE '^[[:space:]]*FROM[[:space:]]' "$file" \
             | grep -viE '@sha256:[0-9a-f]{64}' \
             | grep -viE 'FROM[[:space:]]+scratch' || true)
done < <(find . -path ./.git -prune -o -type f -name 'Dockerfile*' -print0)

if [ -f .pre-commit-config.yaml ]; then
  while IFS= read -r hit; do
    echo "::error::pre-commit-Hook nicht per Commit-SHA gepinnt: .pre-commit-config.yaml:$hit"
    fail=1
  done < <(grep -nE '^[[:space:]]*rev:' .pre-commit-config.yaml \
             | grep -vE 'rev:[[:space:]]*["'\'']?[0-9a-f]{40}([[:space:]"'\'']|$)' || true)
fi

while IFS= read -r hit; do
  echo "::error::Image in Workflow nicht per Digest gepinnt: $hit"
  fail=1
done < <(grep -rnE '^[[:space:]]*[A-Z_]*IMAGE:[[:space:]]' .github/workflows 2>/dev/null \
           | grep -viE '@sha256:[0-9a-f]{64}' || true)

if [ "$fail" -ne 0 ]; then
  echo "Pinning-Prüfung fehlgeschlagen."
  exit 1
fi
echo "Pinning-Prüfung bestanden: alle Actions und pre-commit-Hooks per SHA, alle Images per Digest."
