---
name: archiveboxes-workspace
description: Use this when working across the local ArchiveBox multi-repo workspace, coordinating branches, setup, verification, and repo-specific commands.
---

# ArchiveBoxes Workspace

## Purpose

Use this skill when a task spans multiple repos in `/Users/squash/Local/Code/archiveboxes/new`.

## Shared Rules

- Keep `archivebox` on branch `dev`.
- Keep every other repo on branch `main`.
- Use `uv` and `uv run` for Python commands.
- Do not use system `python`, direct `.venv/bin/python`, or `pip` commands.
- Use existing repo commands, fixtures, helpers, and scripts.
- Do not mock, monkeypatch, fake, simulate, skip, xfail, or weaken tests.
- Verify behavior through real user-facing code paths and real outputs.
- Read each repo `README.md` for the full command surface.

## Development Setup

```bash
uv sync --all-packages --all-extras --all-groups --no-cache --active
```

## User-Facing Setup

Recommended ArchiveBox install:

```bash
cd archivebox
# if not in a local checkout, use `uv tool install archivebox` instead
uv sync
mkdir -p data
cd data
uv run --project .. archivebox init --install
uv run --project .. archivebox add 'https://example.com'
```

Alternative ArchiveBox install methods:

- Docker Compose / Docker
- Homebrew
- Debian package
- pip

## Basic Usage

```bash
cd archivebox/data
uv run --project .. archivebox status

cd ../../abx-dl
uv run abx-dl dl --plugins=title,wget 'https://example.com'
```

<!--pytest.mark.skip(reason="pytest invocation")-->
```bash
cd ../abx-plugins
uv run pytest abx_plugins/plugins/title/tests -q
```

```bash
cd abxpkg
uv run abxpkg load wget
```

<!--pytest.mark.skip(reason="pytest invocation")-->
```bash
cd abxbus
uv run pytest tests -q
```

## Verification

Use targeted repo checks unless the user asks for a full deploy or CI loop:

```bash
git -C archivebox branch --show-current
git -C abx-dl branch --show-current
git -C abx-plugins branch --show-current
git -C abxpkg branch --show-current
git -C abxbus branch --show-current
```

Normal branch pushes run each repository's CI and release workflow. The
monorepo release coordinator advances the dependency chain; do not prepare or
dispatch downstream repositories manually.
