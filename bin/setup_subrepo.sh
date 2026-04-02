#!/usr/bin/env bash
# Drop-in setup script for ArchiveBox sub-repos (abx-dl, abx-plugins, etc.)
#
# Copy this to <your-repo>/bin/setup.sh — it clones the monorepo into ../
# around your repo, then uses the monorepo's setup to clone siblings and sync.
#
# Usage:
#   cd abx-dl && ./bin/setup.sh
#
# After setup, the directory tree looks like:
#   parent/                ← becomes the monorepo checkout
#     pyproject.toml       ← from monorepo (workspace config)
#     bin/setup.sh         ← from monorepo
#     .venv/               ← shared virtualenv
#     abx-dl/              ← your repo (already here)
#     abxbus/              ← cloned by monorepo setup
#     abx-pkg/             ← cloned by monorepo setup
#     abx-plugins/         ← cloned by monorepo setup
#     archivebox/          ← cloned by monorepo setup
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd -- "$REPO_DIR/.." && pwd)"
GITHUB_BASE="${GITHUB_BASE:-https://github.com/ArchiveBox}"

###############################################################################
# Clone monorepo into parent dir (works even though our repo already lives there)
###############################################################################
if [[ -f "$WORKSPACE_DIR/pyproject.toml" ]] && grep -q 'archiveboxes-workspace' "$WORKSPACE_DIR/pyproject.toml" 2>/dev/null; then
    printf 'Monorepo already set up in %s\n' "$WORKSPACE_DIR"
else
    printf 'Cloning monorepo into %s ...\n' "$WORKSPACE_DIR"
    cd "$WORKSPACE_DIR"
    git init -q
    git remote add origin "$GITHUB_BASE/monorepo.git" 2>/dev/null || git remote set-url origin "$GITHUB_BASE/monorepo.git"
    git fetch -q origin main
    # Checkout monorepo files (pyproject.toml, bin/, etc.) without touching sub-repo dirs
    git reset origin/main
    git checkout -- .
    printf 'Monorepo files checked out into %s\n' "$WORKSPACE_DIR"
fi

###############################################################################
# Now run the monorepo's setup.sh to clone siblings and sync
###############################################################################
exec "$WORKSPACE_DIR/bin/setup.sh"
