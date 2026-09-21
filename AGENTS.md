# Workspace Agent Guide

This workspace contains the ArchiveBox development repos. Keep `archivebox` on `dev`; keep every other repo on `main`.

## Checkout Policy

- Work only in the single canonical checkout for each project.
- Do not create additional worktrees or duplicate clones in this workspace.
- Collections may live in ignored `archivebox/data/` or `~/archivebox/data/`. Keep loose scratch data, ad hoc capture outputs, and evidence outside the source checkouts.
- Reuse existing sibling checkouts such as `../ios-archivebox` and `../archivebox-browser-extension`; do not create duplicates to place them under this root.

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

- `android-archivebox`: Kotlin/Compose Android client and share flow. Branch: `main`.
- `electron-archivebox`: Electron desktop client and Docker server controls. Branch: `main`.
- `../ios-archivebox`: Apple client, extensions, and `ServerApp` macOS server companion. Branch: `main`.
- `../archivebox-browser-extension`: WXT extension and persona/browser-state sync. Branch: `main`.
- `docker-archivebox`: deployment definitions. Branch: `main`.
- `docs`: documentation repo; `archivebox-wiki`: separate GitHub wiki repo. Branch: `main`.
- Root `evals`, `bin`, and `skills`: maintained workspace tooling; `old`: historical notes and experiments.

The deleted `archivebox-macos`, `abxpkg-rust`, and feature/docs worktree folders
are not additional projects to recreate. See the README project table for routing.

## App and cross-repo verification

- Android uses Gradle/JDK/Android SDK; Electron uses npm and its package lock; Apple uses Swift/Xcode plus the Safari preparation script; the browser extension uses pnpm/WXT. Use each repository's own documented scripts.
- Test UI work with real local servers, browsers, emulators, or devices. Verify saved artifacts and state changes, not just build success.
- Persona changes cross the server API and Chrome plugin. Verify cookie attributes, explicit clearing versus omitted fields, reuse of browser sessions, and unrelated-cookie preservation.
- Plugins stay independent of ArchiveBox Python. Optional saved-artifact integration must be documented and tolerate absent/malformed artifacts.
- Root setup installs only the five editable Python core projects. It does not provision mobile SDKs or app toolchains.
- Use `.github/release-graph.toml` and the existing coordinator for dependency cascades. Do not manually dispatch downstream releases or treat a local build as a published release.

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
