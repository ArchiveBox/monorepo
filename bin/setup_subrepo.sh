#!/usr/bin/env bash
# Drop-in setup script for ArchiveBox sub-repos (abx-dl, abx-plugins, etc.)
#
# Place this at <your-repo>/bin/setup.sh — it bootstraps a full workspace by
# cloning sibling repos into ../ and generating a workspace pyproject.toml.
#
# Usage:
#   cd abx-dl && ./bin/setup.sh
#
# After setup, the directory tree looks like:
#   parent/
#     pyproject.toml     ← generated workspace config
#     .venv/             ← shared virtualenv
#     abx-dl/            ← your repo (you are here)
#     abxbus/            ← cloned sibling
#     abx-pkg/           ← cloned sibling
#     abx-plugins/       ← cloned sibling
#     archivebox/        ← cloned sibling
#
# If a sibling can't be cloned (network, permissions), it's skipped and
# `uv sync` resolves that dependency from PyPI instead.
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="$(cd -- "$REPO_DIR/.." && pwd)"
GITHUB_BASE="${GITHUB_BASE:-https://github.com/ArchiveBox}"

REPOS=(abxbus abx-pkg abx-plugins abx-dl archivebox)

###############################################################################
clone_repo() {
    local repo_name="$1"
    local target="$WORKSPACE_DIR/$repo_name"

    if [[ -d "$target/.git" ]]; then
        printf '  ✓ %s (existing)\n' "$repo_name"
        return 0
    fi
    if [[ -e "$target" ]]; then
        printf '  ⚠ %s exists but is not a git repo, skipping\n' "$repo_name" >&2
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

###############################################################################
generate_workspace_toml() {
    local toml="$WORKSPACE_DIR/pyproject.toml"

    # Don't overwrite an existing workspace/monorepo config
    if [[ -f "$toml" ]] && grep -q 'tool\.uv\.workspace' "$toml" 2>/dev/null; then
        printf 'Using existing workspace pyproject.toml\n'
        return
    fi

    local members="" sources=""
    for repo in "${REPOS[@]}"; do
        if [[ -f "$WORKSPACE_DIR/$repo/pyproject.toml" ]]; then
            members+="    \"$repo\","$'\n'
            sources+="$repo = { workspace = true }"$'\n'
        fi
    done

    cat > "$toml" <<TOML
[project]
name = "archiveboxes-workspace"
version = "0.0.0"
description = "Auto-generated ArchiveBox workspace (created by $(basename "$REPO_DIR")/bin/setup.sh)"
requires-python = ">=3.11"
dependencies = []

[tool.uv]
package = false

[tool.uv.workspace]
members = [
${members}]

[tool.uv.sources]
${sources}
TOML
    printf 'Generated workspace config at %s\n' "$toml"
}

###############################################################################
printf 'Setting up ArchiveBox workspace from %s\n' "$(basename "$REPO_DIR")"
printf 'Workspace root: %s\n\n' "$WORKSPACE_DIR"

printf 'Cloning sibling repos...\n'
for repo in "${REPOS[@]}"; do
    clone_repo "$repo" || true
done

printf '\n'
generate_workspace_toml

printf '\nSyncing dependencies...\n'
cd "$WORKSPACE_DIR"
uv venv --allow-existing "$WORKSPACE_DIR/.venv"
# shellcheck disable=SC1091
source "$WORKSPACE_DIR/.venv/bin/activate"
uv sync --all-packages --all-extras --no-cache --active

printf '\nDone! Activate with: source %s/.venv/bin/activate\n' "$WORKSPACE_DIR"
