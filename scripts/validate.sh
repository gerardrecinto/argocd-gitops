#!/usr/bin/env bash
# Runs the same checks as .github/workflows/ci.yml, locally, before you push.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v yamllint >/dev/null 2>&1 || { echo "yamllint not found. Install: pip install yamllint" >&2; exit 1; }
command -v kubeconform >/dev/null 2>&1 || { echo "kubeconform not found. See https://github.com/yannh/kubeconform#installation" >&2; exit 1; }

echo "==> yamllint"
yamllint -d relaxed .

echo "==> kubeconform (apps, projects)"
kubeconform -strict -summary \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  -kubernetes-version 1.28.0 \
  apps projects

echo "==> all checks passed"
