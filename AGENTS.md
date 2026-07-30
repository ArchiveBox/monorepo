# Workspace Agent Guide

This workspace contains the ArchiveBox development repos. Keep `archivebox` on `dev`; keep every other repo on `main`.

## Shared Standards

- Use `uv` and `uv run` for Python commands. Do not use system `python`, direct `.venv/bin/python`, or `pip` commands.
- Prefer existing repo patterns, helper APIs, fixtures, scripts, and command surfaces.
- Keep edits focused and minimal. Do not add wrappers, shims, aliases, or extra abstraction layers unless the current code path requires them.
- Do not weaken assertions, skip tests, xfail tests, or accept flaky behavior.
- No mocks, monkeypatches, fakes, simulated handlers, fake binaries, fake hooks, fake buses, or direct shortcuts around user-facing flows.
- Tests and verification should use real CLI commands, REST/API calls, browser UI flows, real hooks, real installs, real subprocesses, real DB rows, real files, and existing fixtures.
- Assertions must verify real correctness: exit codes, returned values, DB state, filesystem contents, field values, rendered output, and side effects.
- Start behavior fixes with a red failing test when a test is requested or practical.
- Trace root causes from observed behavior. Do not paper over failures with retries, wider timeouts, broad fallbacks, or looser assertions.
- Read each repo `README.md` for the full API, setup, release, and usage surface.

## Repos

- `archivebox`: full ArchiveBox app and Docker image. Branch: `dev`.
- `abx-dl`: standalone downloader/extractor CLI. Branch: `main`.
- `abx-plugins`: plugin hook suite and config schemas. Branch: `main`.
- `abxpkg`: binary/package provider library and CLI. Branch: `main`.
- `abxbus`: multi-runtime event bus. Branch: `main`.
- `debian-archivebox`: Debian package wrapper. Branch: `main`.
- `homebrew-archivebox`: Homebrew tap. Branch: `main`.

## Workspace Setup

Run the shared editable environment setup once from the monorepo root:

```bash
uv sync --all-extras --all-groups --no-cache --active
```

For package wrapper repos, read their `README.md` and use the repo scripts:

```bash
cd debian-archivebox
./bin/build_deb.sh

cd ../homebrew-archivebox
./bin/build_brew.sh
```

## Basic Usage

Recommended ArchiveBox CLI install:

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

ArchiveBox collection:

```bash
cd archivebox/data
uv run --project .. archivebox status
uv run --project .. archivebox add 'https://example.com'
uv run --project .. archivebox run
```

Standalone extraction:

```bash
cd abx-dl
uv run abx-dl dl --plugins=title,wget,screenshot 'https://example.com'
```

Plugin inspection:

<!--pytest.mark.skip(reason="pytest invocation")-->
```bash
cd abx-plugins
uv run pytest abx_plugins/plugins/title/tests -q
```

Package provider usage:

```bash
cd abxpkg
uv run abxpkg load wget
uv run abxpkg run wget --version
```

Event bus tests:

<!--pytest.mark.skip(reason="pytest invocation")-->
```bash
cd abxbus
uv run pytest tests -q
```
