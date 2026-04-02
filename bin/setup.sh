#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
GITHUB_BASE="${GITHUB_BASE:-https://github.com/ArchiveBox}"

clone_repo() {
    local target_dir="$1"
    local repo_name="$2"

    if [[ -d "$ROOT_DIR/$target_dir/.git" ]]; then
        printf 'Using existing checkout: %s\n' "$target_dir"
        return
    fi

    if [[ -e "$ROOT_DIR/$target_dir" ]]; then
        printf 'Refusing to overwrite existing path: %s\n' "$ROOT_DIR/$target_dir" >&2
        exit 1
    fi

    printf 'Cloning %s/%s.git -> %s\n' "$GITHUB_BASE" "$repo_name" "$target_dir"
    git clone "$GITHUB_BASE/$repo_name.git" "$ROOT_DIR/$target_dir"
}

while read -r target_dir repo_name; do
    clone_repo "$target_dir" "$repo_name"
done <<'EOF'
abxbus abxbus
abx-pkg abx-pkg
abx-plugins abx-plugins
abx-dl abx-dl
archivebox ArchiveBox
EOF

cd "$ROOT_DIR"
uv venv --allow-existing "$ROOT_DIR/.venv"
# shellcheck disable=SC1091
source "$ROOT_DIR/.venv/bin/activate"
uv sync --all-packages --all-extras --group dev --no-cache --active
