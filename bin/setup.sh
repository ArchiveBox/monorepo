#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
GITHUB_BASE="${GITHUB_BASE:-https://github.com/ArchiveBox}"
MONOREPO_REMOTE="${MONOREPO_REMOTE:-$GITHUB_BASE/monorepo.git}"

is_workspace_root() {
    local repo_root="$1"
    [[ -f "$repo_root/pyproject.toml" ]] && rg -q '^\[tool\.uv\.workspace\]' "$repo_root/pyproject.toml"
}

is_member_repo() {
    case "$(basename "$1")" in
        abxbus | abx-pkg | abx-plugins | abx-dl | archivebox) return 0 ;;
        *) return 1 ;;
    esac
}

monorepo_remote_matches() {
    case "$1" in
        git@github.com:ArchiveBox/monorepo.git | \
        git+ssh://git@github.com/ArchiveBox/monorepo.git | \
        https://github.com/ArchiveBox/monorepo.git)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

bootstrap_monorepo_root() {
    local monorepo_root="$1"
    local origin_url=""

    if [[ -d "$monorepo_root/.git" ]]; then
        origin_url="$(git -C "$monorepo_root" remote get-url origin 2>/dev/null || true)"

        if [[ -n "$origin_url" ]] && ! monorepo_remote_matches "$origin_url"; then
            printf 'Refusing to reuse existing git repo at %s (origin: %s)\n' "$monorepo_root" "$origin_url" >&2
            exit 1
        fi

        if [[ -z "$origin_url" ]]; then
            git -C "$monorepo_root" remote add origin "$MONOREPO_REMOTE"
        fi

        printf 'Updating monorepo root: %s\n' "$monorepo_root"
        if git -C "$monorepo_root" -c pull.rebase=false pull --ff-only --quiet >/dev/null 2>&1; then
            printf 'Updated monorepo root\n'
        else
            printf 'Skipping monorepo pull (local changes, divergent branch, detached HEAD, or no upstream)\n' >&2
        fi
        return
    fi

    printf 'Bootstrapping monorepo root in %s\n' "$monorepo_root"
    git -C "$monorepo_root" init -b main >/dev/null
    git -C "$monorepo_root" remote add origin "$MONOREPO_REMOTE"
    git -C "$monorepo_root" fetch --depth=1 origin main --quiet

    if git -C "$monorepo_root" checkout -B main --track origin/main >/dev/null 2>&1; then
        printf 'Initialized monorepo root\n'
    else
        printf 'Failed to materialize monorepo root in %s; existing files likely conflict with tracked monorepo files\n' "$monorepo_root" >&2
        exit 1
    fi
}

if is_workspace_root "$SCRIPT_REPO_ROOT"; then
    ROOT_DIR="$SCRIPT_REPO_ROOT"
elif is_member_repo "$SCRIPT_REPO_ROOT"; then
    ROOT_DIR="$(cd -- "$SCRIPT_REPO_ROOT/.." && pwd)"
    bootstrap_monorepo_root "$ROOT_DIR"
else
    printf 'Unable to infer monorepo root from script location: %s\n' "$SCRIPT_DIR" >&2
    exit 1
fi

ensure_member_repo() {
    local repo_name="$1"
    local repo_dir="$ROOT_DIR/$repo_name"

    if [[ -d "$repo_dir/.git" ]]; then
        printf 'Updating existing checkout: %s\n' "$repo_name"
        if git -C "$repo_dir" -c pull.rebase=false pull --ff-only --quiet >/dev/null 2>&1; then
            printf 'Updated: %s\n' "$repo_name"
        else
            printf 'Skipping pull for %s (local changes, divergent branch, detached HEAD, or no upstream)\n' "$repo_name" >&2
        fi
        return
    fi

    if [[ -e "$repo_dir" ]]; then
        printf 'Refusing to overwrite existing path: %s\n' "$repo_dir" >&2
        exit 1
    fi

    printf 'Cloning %s/%s.git -> %s\n' "$GITHUB_BASE" "$repo_name" "$repo_name"
    git clone "$GITHUB_BASE/$repo_name.git" "$repo_dir"
}

while read -r repo_name; do
    ensure_member_repo "$repo_name"
done <<'EOF'
abxbus
abx-pkg
abx-plugins
abx-dl
archivebox
EOF

cd "$ROOT_DIR"
uv venv --allow-existing "$ROOT_DIR/.venv"
# shellcheck disable=SC1091
source "$ROOT_DIR/.venv/bin/activate"
uv sync --all-packages --all-extras --no-cache --active
