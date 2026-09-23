from __future__ import annotations

import os
import re
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?$")


@dataclass(frozen=True)
class VersionState:
    candidate_owner: str | None = None
    release_owner: str | None = None
    registry_exists: bool = False


def increment(version: str, scheme: str) -> str:
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise ValueError(f"Unsupported version: {version}")
    major, minor, patch, rc = match.groups()
    if scheme == "patch" and rc is None:
        return f"{major}.{minor}.{int(patch) + 1}"
    if scheme == "rc" and rc is not None:
        return f"{major}.{minor}.{patch}rc{int(rc) + 1}"
    raise ValueError(f"Cannot {scheme}-bump {version}")


def version_key(version: str) -> tuple[int, int, int, int, int]:
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise ValueError(f"Unsupported version: {version}")
    major, minor, patch, rc = match.groups()
    return (int(major), int(minor), int(patch), 0 if rc is not None else 1, int(rc or 0))


def next_rc_after_stable(source: str, stable: str | None) -> str | None:
    """Start a new patch RC cycle when stable has passed the source RC."""
    if stable is None:
        return None
    source_key = version_key(source)
    stable_key = version_key(stable)
    if "rc" in source and stable_key <= source_key:
        return None
    if "rc" not in source and stable_key < source_key:
        return None
    major, minor, patch, _ = VERSION_RE.fullmatch(stable).groups()
    return f"{major}.{minor}.{int(patch) + 1}rc1"


def stable_candidate(source: str, latest_stable: str | None) -> str:
    """Promote RC source and avoid going behind the published stable line."""
    candidate = source.split("rc", 1)[0]
    return max((candidate, latest_stable or candidate), key=version_key)


def classify(head: str, state: VersionState) -> str:
    owners = {owner for owner in (state.candidate_owner, state.release_owner) if owner}
    if len(owners) > 1:
        raise ValueError("Candidate and release tags point to different commits")
    if state.candidate_owner == head:
        return "ready"
    if state.release_owner == head:
        return "reserve"
    if owners or state.registry_exists:
        return "occupied"
    return "reserve"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def remote_owner(ref: str) -> str | None:
    output = git("ls-remote", "origin", ref)
    return output.split()[0] if output else None


def latest_stable_version(tag_prefix: str) -> str | None:
    versions = []
    for line in git("ls-remote", "--tags", "origin", f"refs/tags/{tag_prefix}*").splitlines():
        ref = line.split()[-1].removesuffix("^{}")
        match = re.fullmatch(rf"refs/tags/{re.escape(tag_prefix)}(\d+\.\d+\.\d+)", ref)
        if match:
            versions.append(match.group(1))
    return max(versions, key=version_key) if versions else None


def registry_url(package: str, version: str) -> str:
    return f"https://pypi.org/pypi/{package}/{version}/json?cache_bust={time.time_ns()}"


def registry_exists(package: str, version: str) -> bool:
    request = urllib.request.Request(
        registry_url(package, version),
        headers={"Cache-Control": "no-cache, no-store, max-age=0", "Pragma": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
def state_for(package: str, version: str, tag_prefix: str) -> VersionState:
    return VersionState(
        candidate_owner=remote_owner(f"refs/tags/release-candidate/{version}"),
        release_owner=remote_owner(f"refs/tags/{tag_prefix}{version}^{{}}")
        or remote_owner(f"refs/tags/{tag_prefix}{version}"),
        registry_exists=registry_exists(package, version),
    )


def output(**values: str) -> None:
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        for key, value in values.items():
            print(f"{key}={value}", file=stream)


def main() -> None:
    package = os.environ["RELEASE_PACKAGE"]
    branch = os.environ["RELEASE_BRANCH"]
    tag_prefix = os.environ["RELEASE_TAG_PREFIX"]
    scheme = os.environ["RELEASE_VERSION_SCHEME"]
    head = git("rev-parse", "HEAD")
    remote_head = remote_owner(f"refs/heads/{branch}")
    source_version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    version = source_version
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"Unsupported source version: {version}")
    if remote_head != head:
        output(action="stale", version=version, candidate_tag=f"release-candidate/{version}")
        return

    stable_version = latest_stable_version(tag_prefix)
    if scheme == "patch":
        version = stable_candidate(version, stable_version)
    version_after_stable = next_rc_after_stable(version, stable_version) if scheme == "rc" else None
    if version_after_stable is not None:
        version = version_after_stable
        while classify(head, state_for(package, version, tag_prefix)) == "occupied":
            version = increment(version, scheme)
        action = "bump"
    else:
        action = classify(head, state_for(package, version, tag_prefix))
    while action == "occupied":
        version = increment(version, scheme)
        action = classify(head, state_for(package, version, tag_prefix))
    output(
        action="bump" if version != source_version else action,
        version=version,
        candidate_tag=f"release-candidate/{version}",
    )


if __name__ == "__main__":
    main()
