#!/usr/bin/env bash
# Setup the ArchiveBox workspace by cloning sibling repos and syncing dependencies.
#
# Usage (from monorepo root):
#   ./bin/setup.sh
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
GITHUB_BASE="${GITHUB_BASE:-https://github.com/ArchiveBox}"

REPOS=(abxbus abx-pkg abx-plugins abx-dl archivebox)

clone_repo() {
    local repo_name="$1"
    local target="$ROOT_DIR/$repo_name"

    if [[ -d "$target/.git" ]]; then
        printf '  ✓ %s (existing)\n' "$repo_name"
        return 0
    fi

    if [[ -e "$target" ]]; then
        printf '  ⚠ %s exists but is not a git repo, skipping\n' "$target" >&2
        return 1
    fi

    printf '  Cloning %s/%s.git ...\n' "$GITHUB_BASE" "$repo_name"
    if git clone --quiet "$GITHUB_BASE/$repo_name.git" "$target" 2>/dev/null; then
        return 0
    else
        printf '  ⚠ Could not clone %s — will fall back to PyPI\n' "$repo_name" >&2
        return 1
    fi
}

printf 'Setting up ArchiveBox workspace in %s\n' "$ROOT_DIR"
printf 'Cloning repos...\n'
for repo in "${REPOS[@]}"; do
    clone_repo "$repo" || true
done

printf '\nSyncing dependencies...\n'
cd "$ROOT_DIR"
uv venv --allow-existing "$ROOT_DIR/.venv"
# shellcheck disable=SC1091
source "$ROOT_DIR/.venv/bin/activate"
uv sync --all-packages --no-cache --active
printf '\nWorkspace ready! Activate with: source %s/.venv/bin/activate\n' "$ROOT_DIR"
