#!/usr/bin/env bash
# Setup the ArchiveBox workspace by cloning sibling repos and syncing dependencies.
#
# Can be run from:
#   - The monorepo root:       ./bin/setup.sh
#   - Any sub-repo (abx-dl):   ../bin/setup.sh   (if monorepo is the parent)
#   - Standalone sub-repo:     ./bin/setup.sh     (clones siblings next to it)
#
# If sibling repos are not available, `uv sync` falls back to PyPI versions.
set -euo pipefail

# Resolve the workspace root (parent of the directory containing this script,
# OR the parent of the current repo if invoked via a sub-repo's own setup.sh)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# If this script lives inside a sub-repo's bin/, the workspace root is ../
# If this script lives inside the monorepo's bin/, the workspace root is ../
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

GITHUB_BASE="${GITHUB_BASE:-https://github.com/ArchiveBox}"

# All repos that make up the workspace
REPOS=(abxbus abx-pkg abx-plugins abx-dl archivebox)

###############################################################################
# Clone missing sibling repos (skip any that already exist)
###############################################################################
clone_repo() {
    local repo_name="$1"
    local target="$ROOT_DIR/$repo_name"

    if [[ -d "$target/.git" ]]; then
        printf '  ✓ Using existing checkout: %s\n' "$repo_name"
        return 0
    fi

    if [[ -e "$target" ]]; then
        printf '  ⚠ Path exists but is not a git repo: %s (skipping)\n' "$target" >&2
        return 1
    fi

    printf '  Cloning %s/%s.git -> %s\n' "$GITHUB_BASE" "$repo_name" "$repo_name"
    if git clone --quiet "$GITHUB_BASE/$repo_name.git" "$target" 2>/dev/null; then
        return 0
    else
        printf '  ⚠ Could not clone %s (network error? private repo?) — will use PyPI\n' "$repo_name" >&2
        return 1
    fi
}

printf 'Setting up ArchiveBox workspace in %s\n' "$ROOT_DIR"
printf 'Cloning sibling repos...\n'
for repo in "${REPOS[@]}"; do
    clone_repo "$repo" || true
done

###############################################################################
# Generate workspace pyproject.toml if it doesn't already exist (or is the
# monorepo's own). This lets any sub-repo bootstrap a full workspace.
###############################################################################
generate_workspace_toml() {
    local workspace_toml="$ROOT_DIR/pyproject.toml"

    # If the monorepo's pyproject.toml already exists, don't overwrite it
    if [[ -f "$workspace_toml" ]] && grep -q 'archiveboxes-workspace\|tool\.uv\.workspace' "$workspace_toml" 2>/dev/null; then
        printf '\nUsing existing workspace pyproject.toml\n'
        return
    fi

    printf '\nGenerating workspace pyproject.toml...\n'

    # Build members list from repos that are actually present
    local members=""
    for repo in "${REPOS[@]}"; do
        if [[ -d "$ROOT_DIR/$repo/pyproject.toml" ]] || [[ -f "$ROOT_DIR/$repo/pyproject.toml" ]]; then
            members+="    \"$repo\","$'\n'
        fi
    done

    # Build sources list from repos that are actually present
    local sources=""
    for repo in "${REPOS[@]}"; do
        if [[ -f "$ROOT_DIR/$repo/pyproject.toml" ]]; then
            sources+="$repo = { workspace = true }"$'\n'
        fi
    done

    cat > "$workspace_toml" <<TOML
[project]
name = "archiveboxes-workspace"
version = "0.0.0"
description = "Local uv workspace for ArchiveBox packages"
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
    printf '  Generated %s\n' "$workspace_toml"
}

generate_workspace_toml

###############################################################################
# Create venv and sync
###############################################################################
printf '\nSyncing dependencies...\n'
cd "$ROOT_DIR"
uv venv --allow-existing "$ROOT_DIR/.venv"
# shellcheck disable=SC1091
source "$ROOT_DIR/.venv/bin/activate"
uv sync --all-packages --no-cache --active
printf '\nWorkspace ready! Activate with: source %s/.venv/bin/activate\n' "$ROOT_DIR"
