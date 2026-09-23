"""Verify a tagged browser-extension release and advance its Safari source pin."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


ROOT = Path.cwd()
EDGE = tomllib.loads((ROOT / "coordinator/.github/release-graph.toml").read_text())["source_pins"]["archivebox-browser-extension"]
SOURCE = ROOT / "source"
DOWNSTREAM = ROOT / "downstream"
ARTIFACT = ROOT / "candidate"
SHA = os.environ["SOURCE_SHA"]
TAG = os.environ["SOURCE_TAG"]


def git(directory: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(directory), *args], text=True, capture_output=True, check=check)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def source_release() -> str:
    require(EDGE["repository"].lower() == os.environ["GITHUB_REPOSITORY"].lower(), "Release came from the wrong repository")
    require(re.fullmatch(r"[0-9a-f]{40}", SHA) is not None, "Invalid source SHA")
    require(re.fullmatch(r"v\d+\.\d+\.\d+", TAG) is not None, "Invalid source tag")
    version = TAG[1:]
    require(git(SOURCE, "rev-parse", "HEAD").stdout.strip() == SHA, "Source checkout differs from tested SHA")
    git(SOURCE, "fetch", "origin", "main", "--tags")
    require(git(SOURCE, "rev-parse", f"refs/tags/{TAG}^{{commit}}").stdout.strip() == SHA, "Release tag differs from tested SHA")
    remote_tag = git(SOURCE, "ls-remote", "origin", f"refs/tags/{TAG}", f"refs/tags/{TAG}^{{}}").stdout.splitlines()
    peeled = [line.split()[0] for line in remote_tag if line.endswith(f"refs/tags/{TAG}^{{}}")]
    unpeeled = [line.split()[0] for line in remote_tag if line.endswith(f"refs/tags/{TAG}")]
    require((peeled or unpeeled) == [SHA], "Public release tag moved or differs from tested SHA")
    require(git(SOURCE, "merge-base", "--is-ancestor", SHA, "origin/main", check=False).returncode == 0,
            "Tagged source is not on main")
    package = json.loads((SOURCE / "package.json").read_text())
    require(package["version"] == version, "Tagged package version differs from release tag")
    return version


def verify_artifact(version: str) -> None:
    require(os.environ["ARTIFACT_NAME"] == f"store-packages-{version}", "Artifact name differs from tagged version")
    expected = {f"archivebox-browser-extension-{version}-{browser}.zip" for browser in ("chrome", "edge", "firefox", "sources")}
    actual = {path.name for path in ARTIFACT.iterdir() if path.is_file()}
    require(actual == expected | {"store-package-sha256.txt"}, f"Unexpected package artifact files: {sorted(actual)}")
    digest_lines = (ARTIFACT / "store-package-sha256.txt").read_text().splitlines()
    digests: dict[str, str] = {}
    for line in digest_lines:
        match = re.fullmatch(r"([0-9a-f]{64})  \.output/(archivebox-browser-extension-[^/]+\.zip)", line)
        require(match is not None and match[2] in expected and match[2] not in digests, "Invalid package checksum manifest")
        digests[match[2]] = match[1]
    require(set(digests) == expected, "Checksum manifest does not list each released package exactly once")
    for name, digest in digests.items():
        require(hashlib.sha256((ARTIFACT / name).read_bytes()).hexdigest() == digest, f"Checksum mismatch: {name}")
    for browser in ("chrome", "edge", "firefox"):
        with zipfile.ZipFile(ARTIFACT / f"archivebox-browser-extension-{version}-{browser}.zip") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            require(manifest["version"] == version, f"{browser} package version differs from tagged source")
    with zipfile.ZipFile(ARTIFACT / f"archivebox-browser-extension-{version}-sources.zip") as archive:
        tracked = git(SOURCE, "ls-files", "-z").stdout.split("\0")
        relevant = {name for name in tracked if name in {"package.json", "pnpm-lock.yaml", "wxt.config.ts"}
                    or name.startswith(("entrypoints/", "src/", "public/", "locales/"))}
        require({"package.json", "pnpm-lock.yaml", "wxt.config.ts"} <= relevant, "Tagged source is missing build inputs")
        for name in relevant:
            require(name in archive.namelist() and archive.read(name) == (SOURCE / name).read_bytes(),
                    f"Source package differs from tested commit: {name}")
    print(f"Verified {TAG} at {SHA}, four package checksums and versions, and packaged source bytes")


def advance_pin() -> None:
    branch = EDGE["downstream_branch"]
    pin_file = EDGE["pin_file"]
    require(not git(DOWNSTREAM, "status", "--porcelain").stdout, "Downstream checkout has unrelated edits")
    git(DOWNSTREAM, "config", "user.name", "ArchiveBox Release Bot")
    git(DOWNSTREAM, "config", "user.email", "release-bot@archivebox.io")
    for _ in range(2):
        git(DOWNSTREAM, "fetch", "origin", branch)
        remote = git(DOWNSTREAM, "rev-parse", f"origin/{branch}").stdout.strip()
        if git(DOWNSTREAM, "rev-parse", "HEAD").stdout.strip() != remote:
            # Only this disposable CI checkout and any failed local commit are reset.
            git(DOWNSTREAM, "reset", "--hard", remote)
        path = DOWNSTREAM / pin_file
        original = path.read_text()
        matches = list(re.finditer(r"(?m)^const revision = '([0-9a-f]{40})';", original))
        require(len(matches) == 1, "Expected exactly one Safari extension source pin")
        previous = matches[0][1]
        if previous == SHA:
            print(f"Safari already pins {SHA}")
            return
        require(git(SOURCE, "cat-file", "-e", f"{previous}^{{commit}}", check=False).returncode == 0,
                f"Existing Safari pin {previous} is absent from extension history")
        if git(SOURCE, "merge-base", "--is-ancestor", SHA, previous, check=False).returncode == 0:
            print(f"Safari pin {previous} is newer than {SHA}; delayed release does not roll it back")
            return
        require(git(SOURCE, "merge-base", "--is-ancestor", previous, SHA, check=False).returncode == 0,
                f"Safari pin {previous} diverges from release {SHA}")
        path.write_text(original[:matches[0].start(1)] + SHA + original[matches[0].end(1):])
        changed = git(DOWNSTREAM, "diff", "--name-only").stdout.splitlines()
        require(changed == [pin_file], f"Unrelated downstream edits: {changed}")
        git(DOWNSTREAM, "diff", "--check")
        git(DOWNSTREAM, "add", "--", pin_file)
        git(DOWNSTREAM, "commit", "-m", f"Pin Safari extension to {TAG} ({SHA[:12]})")
        pushed = git(DOWNSTREAM, "push", "origin", f"HEAD:{branch}", check=False)
        if pushed.returncode == 0:
            print(f"Advanced Safari extension pin {previous} -> {SHA} on {EDGE['downstream_repository']}/{branch}")
            return
        git(DOWNSTREAM, "fetch", "origin", branch)
        require(git(DOWNSTREAM, "rev-parse", f"origin/{branch}").stdout.strip() != remote,
                f"Push failed without a concurrent downstream update: {pushed.stderr.strip()}")
    raise SystemExit("Downstream main advanced twice while updating Safari pin")


if __name__ == "__main__":
    require(len(sys.argv) == 2 and sys.argv[1] in {"verify", "pin"}, "Usage: cascade_source_pin.py verify|pin")
    version = source_release()
    verify_artifact(version)
    if sys.argv[1] == "pin":
        advance_pin()
