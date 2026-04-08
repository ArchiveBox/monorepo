#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOS=(abxbus abx-pkg abx-plugins abx-dl archivebox)
TEMP_WORKTREES=()

cleanup() {
    local entry repo worktree
    for entry in "${TEMP_WORKTREES[@]}"; do
        repo="${entry%%|*}"
        worktree="${entry#*|}"
        git -C "${ROOT_DIR}/${repo}" worktree remove --force "${worktree}" 2>/dev/null || rm -rf "${worktree}"
    done
}
trap cleanup EXIT

source_optional_env() {
    if [[ -f "${ROOT_DIR}/.env" ]]; then
        set -a
        # shellcheck disable=SC1091
        source "${ROOT_DIR}/.env"
        set +a
    fi
}

default_branch() {
    local repo_dir="$1"
    git -C "${repo_dir}" symbolic-ref refs/remotes/origin/HEAD | sed 's#^refs/remotes/origin/##'
}

repo_slug() {
    local repo_dir="$1"
    python3 - "${repo_dir}" <<'PY'
import re
import subprocess
import sys

repo_dir = sys.argv[1]
remote = subprocess.check_output(
    ['git', '-C', repo_dir, 'remote', 'get-url', 'origin'],
    text=True,
).strip()

patterns = [
    r'github\.com[:/](?P<slug>[^/]+/[^/.]+)(?:\.git)?$',
    r'github\.com/(?P<slug>[^/]+/[^/.]+)(?:\.git)?$',
]

for pattern in patterns:
    match = re.search(pattern, remote)
    if match:
        print(match.group('slug'))
        raise SystemExit(0)

raise SystemExit(f'Unable to parse GitHub repo slug from remote: {remote}')
PY
}

workflow_file() {
    local repo="$1"
    if [[ "${repo}" == "archivebox" ]]; then
        echo "release-runner.yml"
    else
        echo "release.yml"
    fi
}

current_version() {
    local repo_dir="$1"
    python3 - "${repo_dir}" <<'PY'
from pathlib import Path
import json
import re
import sys

repo_dir = Path(sys.argv[1])
versions = []

pyproject_path = repo_dir / 'pyproject.toml'
if pyproject_path.exists():
    match = re.search(r'^version = "([^"]+)"$', pyproject_path.read_text(), re.MULTILINE)
    if match:
        versions.append(match.group(1))

package_path = repo_dir / 'abxbus-ts' / 'package.json'
if package_path.exists():
    versions.append(json.loads(package_path.read_text())['version'])

def parse(version: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?', version)
    if not match:
        raise SystemExit(f'Unsupported version format: {version}')
    major, minor, patch, rc = match.groups()
    return (int(major), int(minor), int(patch), int(rc) if rc is not None else 10_000)

print(max(versions, key=parse))
PY
}

latest_release_version() {
    local slug="$1"
    local raw_tags
    raw_tags="$(gh api "repos/${slug}/releases?per_page=100" --jq '.[].tag_name' || true)"
    RELEASE_TAGS="${raw_tags}" python3 - <<'PY'
import os
import re

def parse(version: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?', version)
    if not match:
        return (-1, -1, -1, -1)
    major, minor, patch, rc = match.groups()
    return (int(major), int(minor), int(patch), int(rc) if rc is not None else 10_000)

versions = [line.strip() for line in os.environ.get('RELEASE_TAGS', '').splitlines() if line.strip()]
if not versions:
    print('')
else:
    print(max(versions, key=parse))
PY
}

compare_versions() {
    python3 - "$1" "$2" <<'PY'
import re
import sys

def parse(version: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?', version)
    if not match:
        raise SystemExit(f'Unsupported version format: {version}')
    major, minor, patch, rc = match.groups()
    return (int(major), int(minor), int(patch), int(rc) if rc is not None else 10_000)

left, right = sys.argv[1], sys.argv[2]
if parse(left) > parse(right):
    print('gt')
elif parse(left) == parse(right):
    print('eq')
else:
    print('lt')
PY
}

latest_dispatch_run_id() {
    local slug="$1"
    local workflow="$2"
    local branch="$3"
    gh run list \
        --repo "${slug}" \
        --workflow "${workflow}" \
        --event workflow_dispatch \
        --branch "${branch}" \
        --limit 1 \
        --json databaseId \
        --jq '.[0].databaseId // ""'
}

dispatch_release_workflow() {
    local repo="$1"
    local release_dir="$2"
    local slug branch workflow before_id after_id attempts=0

    slug="$(repo_slug "${release_dir}")"
    branch="$(default_branch "${release_dir}")"
    workflow="$(workflow_file "${repo}")"
    before_id="$(latest_dispatch_run_id "${slug}" "${workflow}" "${branch}")"

    gh workflow run "${workflow}" --repo "${slug}" --ref "${branch}"

    while :; do
        after_id="$(latest_dispatch_run_id "${slug}" "${workflow}" "${branch}")"
        if [[ -n "${after_id}" && "${after_id}" != "${before_id}" ]]; then
            gh run watch "${after_id}" --repo "${slug}" --exit-status
            return 0
        fi
        attempts=$((attempts + 1))
        if [[ "${attempts}" -ge 30 ]]; then
            echo "Timed out waiting for ${slug} ${workflow} workflow_dispatch run to start" >&2
            return 1
        fi
        sleep 10
    done
}

copy_untracked_files() {
    local repo_dir="$1"
    local release_dir="$2"
    local relative_path

    while read -r relative_path; do
        [[ -n "${relative_path}" ]] || continue
        mkdir -p "${release_dir}/$(dirname "${relative_path}")"
        cp -R "${repo_dir}/${relative_path}" "${release_dir}/${relative_path}"
    done < <(git -C "${repo_dir}" ls-files --others --exclude-standard)
}

apply_diff_if_present() {
    local release_dir="$1"
    local diff_file="$2"
    if [[ -s "${diff_file}" ]]; then
        git -C "${release_dir}" apply "${diff_file}"
    fi
}

prepare_release_dir() {
    local repo="$1"
    local repo_dir="${ROOT_DIR}/${repo}"
    local branch
    local current_branch
    local release_dir
    local committed_diff
    local staged_diff
    local unstaged_diff

    branch="$(default_branch "${repo_dir}")"
    current_branch="$(git -C "${repo_dir}" branch --show-current)"

    if [[ "${current_branch}" == "${branch}" ]]; then
        echo "${repo_dir}"
        return 0
    fi

    release_dir="$(mktemp -d "${TMPDIR:-/tmp}/${repo}.release.XXXXXX")"
    TEMP_WORKTREES+=("${repo}|${release_dir}")
    git -C "${repo_dir}" worktree add --detach "${release_dir}" "origin/${branch}" >/dev/null

    committed_diff="$(mktemp)"
    staged_diff="$(mktemp)"
    unstaged_diff="$(mktemp)"

    git -C "${repo_dir}" diff --binary "origin/${branch}...HEAD" > "${committed_diff}"
    git -C "${repo_dir}" diff --binary --cached > "${staged_diff}"
    git -C "${repo_dir}" diff --binary > "${unstaged_diff}"

    apply_diff_if_present "${release_dir}" "${committed_diff}"
    apply_diff_if_present "${release_dir}" "${staged_diff}"
    apply_diff_if_present "${release_dir}" "${unstaged_diff}"
    copy_untracked_files "${repo_dir}" "${release_dir}"

    rm -f "${committed_diff}" "${staged_diff}" "${unstaged_diff}"
    echo "${release_dir}"
}

main() {
    local repo
    local release_dir
    local slug
    local current
    local latest
    local relation

    source_optional_env

    for repo in "${REPOS[@]}"; do
        release_dir="$(prepare_release_dir "${repo}")"
        if (
            cd "${release_dir}"
            ./bin/release.sh
        ); then
            continue
        fi

        slug="$(repo_slug "${release_dir}")"
        current="$(current_version "${release_dir}")"
        latest="$(latest_release_version "${slug}")"
        if [[ -z "${latest}" ]]; then
            relation="gt"
        else
            relation="$(compare_versions "${current}" "${latest}")"
        fi

        if [[ "${relation}" != "gt" ]]; then
            echo "Release failed for ${repo} before producing an unreleased version; refusing workflow fallback" >&2
            return 1
        fi

        dispatch_release_workflow "${repo}" "${release_dir}"
    done
}

main "$@"
