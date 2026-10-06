#!/usr/bin/env bash
# Everything CI should run. Fails on the first problem.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Regenerating db/schema.sql from the models"
cd "$ROOT"
BEFORE=""
if [[ -f db/schema.sql ]]; then
  BEFORE="$(cat db/schema.sql)"
fi
python scripts/gen_schema.py
# Compare directly rather than through git, so this works before the first commit.
if [[ -n "$BEFORE" && "$BEFORE" != "$(cat db/schema.sql)" ]]; then
  echo "db/schema.sql was stale. It has been regenerated - commit the change."
  exit 1
fi

echo "==> Regenerating docs/DATA_DICTIONARY.md (fails if a mapped column is missing)"
python scripts/gen_data_dictionary.py

echo "==> Backend lint"
cd "$ROOT/backend"
ruff check app tests
ruff format --check app tests

echo "==> Backend tests"
pytest -q

echo "==> Frontend typecheck"
cd "$ROOT/frontend"
npx tsc --noEmit

echo "==> Frontend build"
npx next build

echo
echo "All checks passed."
