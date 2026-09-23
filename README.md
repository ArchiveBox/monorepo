# ArchiveBox Monorepo

Development workspace for the ArchiveBox server, downloader, plugins, package
providers, native clients, browser extension, documentation, and distribution
wrappers. Each project has its own Git repository; this repository owns the
workspace setup, shared guidance, and release coordination.

## Projects and locations

| Project | Purpose | Canonical location in this workspace |
| --- | --- | --- |
| `archivebox` | Django server, collection storage, admin/API, Docker image | `archivebox/` (`dev`) |
| `abx-dl` | Standalone downloader and generic plugin orchestration | `abx-dl/` (`main`) |
| `abx-plugins` | Capture hooks, config schemas, output preview templates | `abx-plugins/` (`main`) |
| `abxpkg` | Binary discovery, installation, package providers | `abxpkg/` (`main`) |
| `abxbus` | Event bus and schemas; Python, TypeScript, Rust, Go implementations | `abxbus/` (`main`) |
| `android-archivebox` | Kotlin/Compose client and Android share flow | `android-archivebox/` (`main`) |
| `electron-archivebox` | Electron desktop client and Docker-based local server controls | `electron-archivebox/` (`main`) |
| `ios-archivebox` | Swift iOS/iPadOS/macOS client, share/Safari extensions, `ServerApp` companion | Existing sibling `../ios-archivebox/` (`main`) |
| `archivebox-browser-extension` | WXT browser extension, URL collection and persona sync | Existing sibling `../archivebox-browser-extension/` (`main`) |
| `debian-archivebox` | Debian package wrapper | `debian-archivebox/` (`main`) |
| `homebrew-archivebox` | Homebrew tap and bottles | `homebrew-archivebox/` (`main`) |
| `docker-archivebox` | Docker deployment definitions | `docker-archivebox/` (`main`) |
| `docs` | Documentation and GitHub wiki: one checkout, two synchronized remotes | `docs/` (`main`) |

Use one canonical checkout per project at the locations above. Apple server
work belongs in `../ios-archivebox/ServerApp`. Root `ci-dashboard/`, `bin/`, and `skills/`
contain workspace tooling; `old/` contains historical design notes and experiments.

The root checkout is a `uv` project with editable path dependencies on all five
packages. Its generated local `uv.lock` and `.venv` provide one consistent
development environment, while each nested repo remains an independent `uv`
project whose committed `uv.lock` is authoritative for CI and release. The root
lock is intentionally ignored because independently released versions change
continuously.

## Setup

<!--
```bash
cd "$(mktemp -d)"
export UV_PROJECT_ENVIRONMENT="$(mktemp -d)/.venv"
unset VIRTUAL_ENV
```
-->
<!--pytest-codeblocks:cont-->
```bash
git clone https://github.com/ArchiveBox/monorepo.git
cd monorepo
./bin/setup.sh
```

`bin/setup.sh` manages only the five Python core repos listed in `REPO_NAMES`; app, docs, and packaging repos use their own setup instructions. It clones missing core repos, tries to fast-forward existing checkouts with `git pull --ff-only` while ignoring pull failures caused by local repo state, refreshes `bin/setup_monorepo.sh` hardlinks inside each member repo so they always match the root script, creates the root `.venv`, uses `abxpkg` to project required host build tools into `.venv/abxpkg/env/bin`, and then syncs the editable packages into the shared monorepo env.

```bash
uv sync --all-extras --all-groups --no-cache --active
```

Each member repo also gets a `bin/setup_monorepo.sh` hardlink back to the root script. When run from inside a member checkout, it bootstraps `../` into a real `ArchiveBox/monorepo` git checkout first, then continues with the normal sibling repo setup.

<!--
```bash
cd "$(mktemp -d)"
export UV_PROJECT_ENVIRONMENT="$(mktemp -d)/.venv"
unset VIRTUAL_ENV
```
-->
<!--pytest-codeblocks:cont-->
```bash
git clone https://github.com/ArchiveBox/abxbus
cd abxbus
./bin/setup_monorepo.sh
```

## Workflow Rules

- Use one canonical checkout per project; do not create extra clones or worktrees.
- Keep intentional collections under ignored `archivebox/data/` or `~/archivebox/data/`. Put one-off evidence and scratch outputs outside the source tree (for example, `../workspace-artifacts/` or the system temporary directory).
- Keep runtime databases, profiles, captures, build outputs, and VM images out of commits. `.gitignore` protects untracked artifacts; it cannot remove objects already retained by history or local checkpoint refs.
- Always use `uv` for Python work. Do not use `pip` or raw `python3 ...` directly.
- If you need Python directly, use `uv run python ...`.
- Do not use `py_compile` for syntax checks. Use `uv run prek run --all-files`.
- `prek` is the main sweep command. It runs the repo checks together, including tools like Ruff, Ty, Pyright, Prettier, and related hooks.
- Run tests with `uv run pytest -xs ...` and keep `-x` failfast on by default so you do not sit through long suites after the first real regression.
- Prefer targeted test selection while iterating, for example `uv run pytest -xs abx-dl/tests/test_cli.py::test_download`.
- `abxbus/abxbus-ts` is a TypeScript implementation. Use `pnpm` inside that folder, never `npm`.

## Branches

- `archivebox` develops on `dev`.
- Every other project listed above develops on `main`. Preserve existing uncommitted work when switching context.

## Automatic Releases

`abxpkg`, `abx-plugins`, `abx-dl`, `electron-archivebox`, `android-archivebox`,
and both apps in `ios-archivebox` share the `1.13.0` release baseline. Subsequent
patch releases remain independent; matching versions do not imply matching
release dates or replace dependency compatibility pins. `archivebox` and `abxbus`
keep their own version series. App build counters and the bundled ArchiveBox
engine version remain separate from the app marketing version.

Publish Python packages in dependency order (`abxpkg` → `abx-plugins` → `abx-dl`).
The existing cascade updates exact dependency pins and lockfile artifacts only
after publication; do not point them at unpublished baseline packages.

Push source changes only to the repository you are working in. Its normal CI
reserves and bumps versions automatically, then
publishes the exact tested release and then calls the central release coordinator
in this monorepo. The coordinator discovers the immediate dependent from
`.github/release-graph.toml`, updates that repository's dependency pins, and
lets its ordinary push CI continue the chain.

ArchiveBox stable releases are prepared on `main`; the coordinator routes downloader
updates there. CI chooses the next available version from source and release history,
including promoting RC source when it lands on `main`. No version target or manual
dependency pin changes are needed.

Do not manually push, dispatch, or prepare downstream repositories. Package
repositories know only their own release identity; the monorepo exclusively owns
dependency order and downstream repository names.

## App development and verification

Read each app's README and development guide before running its build:

- Android: JDK 17 and Android SDK; run `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug`. Use a real emulator/device for sharing, connection discovery, and authenticated browsing acceptance.
- Electron: use the committed `package-lock.json` with `npm ci`, then `npm run lint` and `npm start`. `npm run make` packages the app. Test server start/stop and connection flows against a real Docker engine/server when those paths change.
- Apple: in `../ios-archivebox`, run `node scripts/prepare-safari.mjs`, `swift test`, and open `ArchiveBox.xcodeproj`. Use the ArchiveBox/ArchiveBoxMac targets for clients; the optional server companion has its own `ServerApp/README.md` and prepare/build scripts. Signing, TestFlight, and notarization are separate from local build acceptance.
- Browser extension: use its pnpm lockfile and package scripts (`pnpm compile`, `pnpm build`, `pnpm test`); Safari integration is prepared by the Apple repo. Verify persona/cookie sync against the actual local server and browser.

App connection work spans the server API, browser-session authentication, client
connection storage, discovery, and share flows. Keep credentials scoped to the
selected server. Server acceptance of a URL is not proof that capture completed.
For preview changes, verify real saved outputs in the snapshot detail page,
including expanded stack cards, missing optional artifacts, and raw-file links.

## Shared Runtime State

- `abx-plugins`, `abx-dl`, and `archivebox` share `~/.config/abx` and the active XDG cache directory for dynamic runtime dependencies, cached/derived env config, temp files, sockets, and related runtime state.

## Repo Guide

### `abxbus`

- Purpose: shared event bus and event schema layer used across the stack.
- Workspace dependencies: none.
- Workspace dependents: `abx-dl`, `archivebox`.
- Usage: keep it transport- and application-agnostic. Python lives in `abxbus/`; the TypeScript implementation lives in `abxbus/abxbus-ts`.

### `abxpkg`

- Purpose: system package and binary management layer.
- Workspace dependencies: none.
- Workspace dependents: `abx-plugins`, `abx-dl`, `archivebox`.
- Usage: always use `abxpkg` for package management, binary discovery, version checks, and installation flows instead of `shutil.which`, ad hoc shell probes, or direct `subprocess.call(...)` commands.

### `abx-plugins`

- Purpose: plugin definitions, manifests, adapters, and shared plugin helpers.
- Workspace dependencies: `abxpkg`.
- Workspace dependents: `abx-dl`, `archivebox`.
- Usage: plugins are generic workers. They must not depend on `abx-dl`, `archivebox`, or any app-specific runtime knowledge.
- Inputs/outputs: plugins receive input via env vars, CLI args, and filesystem state; they emit records and progress info to stdout/stderr and write outputs to the filesystem.
- Internal structure: plugins may depend on each other when needed, but no circular loops. Shared helpers may live in `plugins/base/utils.*`.
- Dependency policy: do not add plugin runtime dependencies to `abx-plugins/pyproject.toml` and do not create a root `package.json`. Plugin runtime dependencies belong in `plugins/<pluginname>/config.json` under `required_binaries`, and are installed at runtime via `abxpkg`.

### `abx-dl`

- Purpose: generic plugin orchestration runtime.
- Workspace dependencies: `abxbus`, `abxpkg`, `abx-plugins`.
- Workspace dependents: `archivebox`.
- Usage: this is the orchestration layer for installs, runs, progress, and events. Keep it generic.
- Boundary: `abx-dl` must not know about `archivebox`, specific plugins, or individual plugin resources. It should orchestrate plugin execution through stable generic interfaces only.

### `archivebox`

- Purpose: end-user application and persistence layer.
- Workspace dependencies: `abxbus`, `abxpkg`, `abx-plugins`, `abx-dl`.
- Workspace dependents: none in this workspace.
- Usage: `archivebox` uses `abx-dl` to install plugin binaries, run snapshot downloads, and handle plugin-facing runtime work.
- Boundary: `archivebox` should never know about individual plugins or their resources such as Chrome, and it should not re-implement functionality that already belongs in `abx-dl`.
- Runtime model: `archivebox` listens to the `abx-dl` event stream, projects events into its database, and injects events back to steer `abx-dl`. `abx-dl` owns the actual orchestration runtime for snapshot execution and installs.

## Documentation and wiki synchronization

`docs/` is the single canonical checkout for both `ArchiveBox/docs.git` (`origin`)
and `ArchiveBox/ArchiveBox.wiki.git` (`wiki`). Local `main` publishes to `master`
on both remotes.

Configure a fresh checkout once:

```bash
cd docs
git remote add wiki https://github.com/ArchiveBox/ArchiveBox.wiki.git
git config --replace-all remote.origin.pushurl https://github.com/ArchiveBox/docs.git
git config --add remote.origin.pushurl https://github.com/ArchiveBox/ArchiveBox.wiki.git
git config remote.origin.push refs/heads/main:refs/heads/master
git config remote.wiki.push refs/heads/main:refs/heads/master
git branch --set-upstream-to=origin/master main
```

Before editing, `git fetch --all` and merge changes from both `origin/master` and
`wiki/master`, including edits made through GitHub's wiki UI. Publish with `git push`
to update both destinations. These pushes are sequential, not atomic: if either
fails, reconcile that remote and push again. Verify `git ls-remote origin refs/heads/master`
and `git ls-remote wiki refs/heads/master` report the same commit before considering
publication complete. Do not force-push or mirror unrelated refs.
