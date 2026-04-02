#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
GITHUB_BASE="${GITHUB_BASE:-https://github.com/ArchiveBox}"

clone_repo() {
    local repo_name="$1"

    if [[ -d "$ROOT_DIR/$repo_name/.git" ]]; then
        printf 'Using existing checkout: %s\n' "$repo_name"
        return
    fi

    if [[ -e "$ROOT_DIR/$repo_name" ]]; then
        printf 'Refusing to overwrite existing path: %s\n' "$ROOT_DIR/$repo_name" >&2
        exit 1
    fi

    printf 'Cloning %s/%s.git -> %s\n' "$GITHUB_BASE" "$repo_name" "$repo_name"
    git clone "$GITHUB_BASE/$repo_name.git" "$ROOT_DIR/$repo_name"
}

while read -r repo_name; do
    clone_repo "$repo_name"
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
uv sync --all-packages --all-extras --group dev --no-cache --active
