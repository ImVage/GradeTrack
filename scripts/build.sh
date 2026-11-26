#!/usr/bin/env bash
# Baut das GradeTrack-Image aus dem aktuellen Git-Stand.
#
#   bash scripts/build.sh            # Image gradetrack:<commit> und gradetrack:latest
#   IMAGE=meinname bash scripts/build.sh
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-gradetrack}"
REVISION="$(git rev-parse --short HEAD)"

# Uncommittete Änderungen würden im Image landen, aber nicht zum Commit-Tag passen.
if [ -n "$(git status --porcelain)" ]; then
  echo "Warnung: Es gibt uncommittete Änderungen, das Image entspricht nicht exakt ${REVISION}." >&2
fi

docker build \
  --label "org.opencontainers.image.revision=${REVISION}" \
  --label "org.opencontainers.image.source=https://github.com/ImVage/GradeTrack" \
  --tag "${IMAGE}:${REVISION}" \
  --tag "${IMAGE}:latest" \
  .

echo "Fertig: ${IMAGE}:${REVISION} (auch als ${IMAGE}:latest)"
