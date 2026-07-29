#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOS=(abxbus abxpkg abx-plugins abx-dl archivebox)
ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-${ROOT_DIR}/.venv/abxpkg}"
GIT_BINARY=""
GH_BINARY=""
UV_BINARY=""
DOCKER_BINARY=""

target_branch() {
    if [[ "$1" == "archivebox" ]]; then
        printf 'dev\n'
    else
        printf 'main\n'
    fi
}

repo_slug() {
    if [[ "$1" == "archivebox" ]]; then
        printf 'ArchiveBox/ArchiveBox\n'
    else
        printf 'ArchiveBox/%s\n' "$1"
    fi
}

ci_workflow() {
    case "$1" in
        abxbus | abx-dl | archivebox) printf 'ci.yml\n' ;;
        abxpkg) printf 'tests.yml\n' ;;
        abx-plugins) printf 'test-parallel.yml\n' ;;
        *) return 1 ;;
    esac
}

current_version() {
    sed -nE 's/^version = "([^"]+)".*/\1/p' "${ROOT_DIR}/$1/pyproject.toml" | head -n 1
}

version_at_origin() {
    local repo="$1" branch="$2"
    "$GIT_BINARY" -C "${ROOT_DIR}/${repo}" show "origin/${branch}:pyproject.toml" \
        | sed -nE 's/^version = "([^"]+)".*/\1/p' \
        | head -n 1
}

resolve_tools() {
    local providers
    case "${OSTYPE}" in
        darwin*) providers="env,brew" ;;
        linux*) providers="env,apt" ;;
        *)
            echo "Unsupported release-train platform: ${OSTYPE}" >&2
            return 1
            ;;
    esac

    mkdir -p "${ABXPKG_LIB_DIR}/env/bin"
    uv tool run --no-cache --from "${ROOT_DIR}/abxpkg" abxpkg env \
        --install \
        --no-cache \
        --json \
        --lib="${ABXPKG_LIB_DIR}" \
        --binproviders="${providers}" \
        uv git gh docker >/dev/null

    GIT_BINARY="${ABXPKG_LIB_DIR}/env/bin/git"
    GH_BINARY="${ABXPKG_LIB_DIR}/env/bin/gh"
    UV_BINARY="${ABXPKG_LIB_DIR}/env/bin/uv"
    DOCKER_BINARY="${ABXPKG_LIB_DIR}/env/bin/docker"
    for binary in "$GIT_BINARY" "$GH_BINARY" "$UV_BINARY" "$DOCKER_BINARY"; do
        [[ -L "$binary" && -x "$binary" ]] || {
            echo "abxpkg did not project an executable symlink: ${binary}" >&2
            return 1
        }
    done
    "$GH_BINARY" auth status >/dev/null
}

validate_repo() {
    local repo="$1" repo_dir="${ROOT_DIR}/$1" branch slug remote current_branch
    branch="$(target_branch "$repo")"
    slug="$(repo_slug "$repo")"

    [[ -d "${repo_dir}/.git" ]] || {
        echo "Missing member checkout: ${repo_dir}" >&2
        return 1
    }
    current_branch="$("$GIT_BINARY" -C "$repo_dir" branch --show-current)"
    [[ "$current_branch" == "$branch" ]] || {
        echo "${repo} must be on ${branch}, found ${current_branch:-detached HEAD}" >&2
        return 1
    }
    [[ -z "$("$GIT_BINARY" -C "$repo_dir" status --short)" ]] || {
        echo "${repo} has uncommitted changes; commit the version, dependency, and lock updates first" >&2
        return 1
    }
    remote="$("$GIT_BINARY" -C "$repo_dir" remote get-url origin)"
    case "$remote" in
        "https://github.com/${slug}.git" | \
        "git@github.com:${slug}.git" | \
        "git+ssh://git@github.com/${slug}.git")
            ;;
        *)
            echo "${repo} origin is ${remote}, expected ${slug}" >&2
            return 1
            ;;
    esac

    "$GIT_BINARY" -C "$repo_dir" fetch --quiet --no-tags origin \
        "+refs/heads/${branch}:refs/remotes/origin/${branch}"
    "$GIT_BINARY" -C "$repo_dir" merge-base --is-ancestor "origin/${branch}" HEAD || {
        echo "${repo} diverges from origin/${branch}; refusing to release" >&2
        return 1
    }
}

is_ahead() {
    local repo="$1" branch
    branch="$(target_branch "$repo")"
    [[ "$("$GIT_BINARY" -C "${ROOT_DIR}/${repo}" rev-parse HEAD)" != \
       "$("$GIT_BINARY" -C "${ROOT_DIR}/${repo}" rev-parse "origin/${branch}")" ]]
}

first_changed_index() {
    local requested="${1:-}" index repo
    if [[ -n "$requested" ]]; then
        for index in "${!REPOS[@]}"; do
            [[ "${REPOS[$index]}" == "$requested" ]] && {
                printf '%s\n' "$index"
                return 0
            }
        done
        echo "Unknown release-train member: ${requested}" >&2
        return 1
    fi

    for index in "${!REPOS[@]}"; do
        repo="${REPOS[$index]}"
        if is_ahead "$repo"; then
            printf '%s\n' "$index"
            return 0
        fi
    done
    return 1
}

validate_release_suffix() {
    local first_index="$1" index repo branch current previous
    for ((index = first_index; index < ${#REPOS[@]}; index++)); do
        repo="${REPOS[$index]}"
        branch="$(target_branch "$repo")"
        is_ahead "$repo" || {
            echo "${repo} must be rebuilt because ${REPOS[$first_index]} changed" >&2
            return 1
        }
        current="$(current_version "$repo")"
        previous="$(version_at_origin "$repo" "$branch")"
        [[ -n "$current" && -n "$previous" && "$current" != "$previous" ]] || {
            echo "${repo} must have a new version before entering the release train" >&2
            return 1
        }
        (
            cd "${ROOT_DIR}/${repo}"
            "$UV_BINARY" lock --check --no-cache
        )
    done
}

validate_dependency_chain() {
    ROOT_DIR="$ROOT_DIR" "$UV_BINARY" run --no-cache --no-project python - <<'PY'
import os
import re
import tomllib
from pathlib import Path

root = Path(os.environ["ROOT_DIR"])
repos = ("abxbus", "abxpkg", "abx-plugins", "abx-dl", "archivebox")
projects = {
    repo: tomllib.loads((root / repo / "pyproject.toml").read_text())
    for repo in repos
}
versions = {repo: projects[repo]["project"]["version"] for repo in repos}

exact_dependencies = {
    "abx-plugins": {"abxbus": versions["abxbus"], "abxpkg": versions["abxpkg"]},
    "abx-dl": {"abxbus": versions["abxbus"], "abx-plugins": versions["abx-plugins"]},
    "archivebox": {"abxbus": versions["abxbus"], "abx-dl": versions["abx-dl"]},
}
for repo, expected in exact_dependencies.items():
    dependencies = projects[repo]["project"]["dependencies"]
    for package, version in expected.items():
        pattern = re.compile(rf"{re.escape(package)}=={re.escape(version)}(?:$|[; ])")
        if not any(pattern.match(dependency) for dependency in dependencies):
            raise SystemExit(f"{repo} must depend on {package}=={version}")

for repo in repos[1:]:
    lock = tomllib.loads((root / repo / "uv.lock").read_text())
    locked = {package["name"]: package["version"] for package in lock["package"]}
    for dependency in repos[: repos.index(repo)]:
        if dependency in locked and locked[dependency] != versions[dependency]:
            raise SystemExit(
                f"{repo}/uv.lock has {dependency}=={locked[dependency]}, "
                f"expected {versions[dependency]}"
            )
PY
}

wait_for_run() {
    local slug="$1" workflow="$2" event="$3" sha="$4"
    local run_id=""
    for _ in {1..30}; do
        run_id="$("$GH_BINARY" run list \
            --repo "$slug" \
            --workflow "$workflow" \
            --event "$event" \
            --commit "$sha" \
            --limit 1 \
            --json databaseId \
            --jq '.[0].databaseId // ""')"
        [[ -n "$run_id" ]] && break
        sleep 2
    done
    [[ -n "$run_id" ]] || {
        echo "No ${workflow} ${event} run appeared for ${slug}@${sha}" >&2
        return 1
    }
    "$GH_BINARY" run watch "$run_id" --repo "$slug" --exit-status
}

verify_python_release() {
    local repo="$1" version="$2" verify_dir
    verify_dir="$(mktemp -d)"
    (
        cd "$verify_dir"
        case "$repo" in
            abxbus)
                "$UV_BINARY" run --no-cache --isolated --no-project \
                    --with "abxbus==${version}" python - "$version" <<'PY'
import importlib.metadata
import sys
import abxbus

assert importlib.metadata.version("abxbus") == sys.argv[1]
PY
                ;;
            abxpkg)
                [[ "$("$UV_BINARY" tool run --no-cache --from "abxpkg==${version}" abxpkg --version)" == "$version" ]]
                ;;
            abx-plugins)
                "$UV_BINARY" run --no-cache --isolated --no-project \
                    --with "abx-plugins==${version}" python - <<'PY'
from abx_plugins import get_plugins_dir

assert get_plugins_dir().is_dir()
PY
                ;;
            abx-dl)
                [[ "$("$UV_BINARY" tool run --no-cache --from "abx-dl==${version}" abx-dl --version)" == "$version" ]]
                ;;
            archivebox)
                [[ "$("$UV_BINARY" tool run --no-cache --prerelease allow \
                    --from "archivebox==${version}" archivebox --version)" == "$version" ]]
                ;;
        esac
    )
}

verify_docker_release() {
    local repo="$1" version="$2" image output
    if [[ "$repo" == "abx-dl" ]]; then
        image="archivebox/abx-dl:${version}"
    elif [[ "$repo" == "archivebox" ]]; then
        image="archivebox/archivebox:${version}"
    else
        return 0
    fi
    "$DOCKER_BINARY" buildx imagetools inspect "$image" >/dev/null
    output="$("$DOCKER_BINARY" run --rm "$image" --version)"
    [[ "$output" == "$version" ]] || {
        echo "${image} reported version ${output}, expected ${version}" >&2
        return 1
    }
}

release_repo() {
    local repo="$1" repo_dir="${ROOT_DIR}/$1" branch slug workflow sha version
    branch="$(target_branch "$repo")"
    slug="$(repo_slug "$repo")"
    workflow="$(ci_workflow "$repo")"
    sha="$("$GIT_BINARY" -C "$repo_dir" rev-parse HEAD)"
    version="$(current_version "$repo")"

    echo "Releasing ${slug}@${sha} as ${version}"
    "$GIT_BINARY" -C "$repo_dir" push origin "HEAD:${branch}"
    wait_for_run "$slug" "$workflow" push "$sha"
    wait_for_run "$slug" release.yml workflow_run "$sha"

    sleep 60
    verify_python_release "$repo" "$version"
    verify_docker_release "$repo" "$version"
    echo "Verified ${repo} ${version}"
}

main() {
    local requested="${1:-}" first_index index repo
    [[ "$#" -le 1 ]] || {
        echo "Usage: $0 [abxbus|abxpkg|abx-plugins|abx-dl|archivebox]" >&2
        return 1
    }

    resolve_tools
    for repo in "${REPOS[@]}"; do
        validate_repo "$repo"
    done
    if ! first_index="$(first_changed_index "$requested")"; then
        echo "All member repositories already match their release branches"
        return 0
    fi
    validate_release_suffix "$first_index"
    validate_dependency_chain

    for ((index = first_index; index < ${#REPOS[@]}; index++)); do
        release_repo "${REPOS[$index]}"
    done
}

main "$@"
