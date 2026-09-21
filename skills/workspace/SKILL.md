---
name: archiveboxes-workspace
description: Use this when working across the local ArchiveBox multi-repo workspace, coordinating branches, setup, verification, and repo-specific commands.
---

# ArchiveBoxes Workspace

## Purpose

Use this skill for changes spanning the ArchiveBox server, libraries, plugins,
apps, extension, packaging, or docs. Read the root README's project table first;
it is the canonical project/location map. This local workspace also uses existing
sibling checkouts for `ios-archivebox` and `archivebox-browser-extension`.

## Shared Rules

- Work in one canonical checkout per project. Do not create worktrees or duplicate clones.
- Keep `archivebox` on branch `dev`.
- Keep every other repo on branch `main`.
- Use `uv` and `uv run` for Python commands.
- Do not use system `python`, direct `.venv/bin/python`, or `pip` commands.
- Use existing repo commands, fixtures, helpers, and scripts.
- Do not mock, monkeypatch, fake, simulate, skip, xfail, or weaken tests.
- Verify behavior through real user-facing code paths and real outputs.
- Read each repo `README.md` for the full command surface.

## Route the work

- Capture lifecycle and generic orchestration: `abx-dl`; plugin behavior, Chrome, and preview templates: `abx-plugins`; persistence/admin/API: `archivebox`.
- Android: `android-archivebox` (Gradle). Desktop cross-platform: `electron-archivebox` (npm/Electron). Apple clients and macOS server: existing `../ios-archivebox` (Swift/Xcode and `ServerApp`). Browser integration: existing `../archivebox-browser-extension` (pnpm/WXT).
- Packaging: `debian-archivebox`, `homebrew-archivebox`, `docker-archivebox`. Docs and wiki are distinct repositories. Do not recreate deleted historical docs worktrees or the macOS prototype.
- Consult each project's README, AGENTS, and relevant development guide for its toolchain and test surface; the shared uv setup covers only the Python core.

## Keep source and runtime data separate

Intentional collections in ignored `archivebox/data/` or `~/archivebox/data/`
are supported. Place temporary evidence/scratch captures outside source checkouts.
Do not put databases, downloaded browser profiles, VM images, or backup archives
at the monorepo root. Check ignored files as well as `git status` during cleanup;
a clean status is not evidence of an uncluttered directory. Preserve unique
source work before removing an old checkout. Do not remove tracked test fixtures
just because they resemble collection data.

## Development Setup

```bash
uv sync --all-extras --all-groups --no-cache --active
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

For app/server changes, manually exercise the affected flow against a local
server in addition to targeted tests. For persona sync, check explicit empty
versus omitted auth fields, cookie reconciliation, browser-session reuse, and
preferences in a real browser. For previews, inspect real captures with optional
outputs both present and absent. Report pending device/runtime verification.

Normal branch pushes run each repository's CI and release workflow. The
monorepo release coordinator advances the dependency chain; do not prepare or
dispatch downstream repositories manually.
