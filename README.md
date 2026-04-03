# ArchiveBox Monorepo

Umbrella `uv` workspace for local development across:

- [`abxbus`](https://github.com/ArchiveBox/abxbus)
- [`abx-pkg`](https://github.com/ArchiveBox/abx-pkg)
- [`abx-plugins`](https://github.com/ArchiveBox/abx-plugins)
- [`abx-dl`](https://github.com/ArchiveBox/abx-dl)
- [`archivebox`](https://github.com/ArchiveBox/archivebox)

This repo only tracks the workspace root files. Each package stays in its own Git repository and is cloned next to the root workspace.

## Setup

```bash
git clone git@github.com:ArchiveBox/monorepo.git
cd monorepo
./bin/setup.sh
```

`bin/setup.sh` clones missing sibling repos, tries to fast-forward existing checkouts with `git pull --ff-only` while ignoring pull failures caused by local repo state, refreshes `bin/setup_monorepo.sh` hardlinks inside each member repo so they always match the root script, creates the root `.venv`, makes a best-effort attempt to run `sudo apt install libldap2-dev || brew install openldap`, and then runs:

```bash
uv sync --all-packages --all-extras --no-cache --active
```

If the extras sync still fails, the script retries automatically without `--all-extras`. That gets the workspace up even when LDAP build deps are unavailable, but `archivebox[ldap]` will remain unavailable until you install them manually.

Each member repo also gets a `bin/setup_monorepo.sh` hardlink back to the root script. When run from inside a member checkout, it bootstraps `../` into a real `ArchiveBox/monorepo` git checkout first, then continues with the normal sibling repo setup.

```bash
git clone https://github.com/ArchiveBox/abxbus
cd abxbus
./bin/setup_monorepo.sh
```

## Workflow Rules

- Always use `uv` for everything. Do not use `pip` or raw `python3 ...` directly.
- If you need Python directly, use `uv run python ...`.
- Do not use `py_compile` for syntax checks. Use `uv run prek run --all-files`.
- `prek` is the main sweep command. It runs the repo checks together, including tools like Ruff, Ty, Pyright, Prettier, and related hooks.
- Run tests with `uv run pytest -xs ...` and keep `-x` failfast on by default so you do not sit through long suites after the first real regression.
- Prefer targeted test selection while iterating, for example `uv run pytest -xs abx-dl/tests/test_cli.py::test_download`.
- `abxbus/abxbus-ts` is a TypeScript implementation. Use `pnpm` inside that folder, never `npm`.

## Branches

- `archivebox` develops on `dev`.
- `abxbus`, `abx-pkg`, `abx-plugins`, and `abx-dl` develop on `main`.

## Shared Runtime State

- `abx-plugins`, `abx-dl`, and `archivebox` share `~/.config/abx` and the active XDG cache directory for dynamic runtime dependencies, cached/derived env config, temp files, sockets, and related runtime state.

## Repo Guide

### `abxbus`

- Purpose: shared event bus and event schema layer used across the stack.
- Workspace dependencies: none.
- Workspace dependents: `abx-dl`, `archivebox`.
- Usage: keep it transport- and application-agnostic. Python lives in `abxbus/`; the TypeScript implementation lives in `abxbus/abxbus-ts`.

### `abx-pkg`

- Purpose: system package and binary management layer.
- Workspace dependencies: none.
- Workspace dependents: `abx-plugins`, `abx-dl`, `archivebox`.
- Usage: always use `abx-pkg` for package management, binary discovery, version checks, and installation flows instead of `shutil.which`, ad hoc shell probes, or direct `subprocess.call(...)` commands.

### `abx-plugins`

- Purpose: plugin definitions, manifests, adapters, and shared plugin helpers.
- Workspace dependencies: `abx-pkg`.
- Workspace dependents: `abx-dl`, `archivebox`.
- Usage: plugins are generic workers. They must not depend on `abx-dl`, `archivebox`, or any app-specific runtime knowledge.
- Inputs/outputs: plugins receive input via env vars, CLI args, and filesystem state; they emit records and progress info to stdout/stderr and write outputs to the filesystem.
- Internal structure: plugins may depend on each other when needed, but no circular loops. Shared helpers may live in `plugins/base/utils.*`.
- Dependency policy: do not add plugin runtime dependencies to `abx-plugins/pyproject.toml` and do not create a root `package.json`. Plugin runtime dependencies belong in `plugins/<pluginname>/config.json` under `required_binaries`, and are installed at runtime via `abx-pkg`.

### `abx-dl`

- Purpose: generic plugin orchestration runtime.
- Workspace dependencies: `abxbus`, `abx-pkg`, `abx-plugins`.
- Workspace dependents: `archivebox`.
- Usage: this is the orchestration layer for installs, runs, progress, and events. Keep it generic.
- Boundary: `abx-dl` must not know about `archivebox`, specific plugins, or individual plugin resources. It should orchestrate plugin execution through stable generic interfaces only.

### `archivebox`

- Purpose: end-user application and persistence layer.
- Workspace dependencies: `abxbus`, `abx-pkg`, `abx-plugins`, `abx-dl`.
- Workspace dependents: none in this workspace.
- Usage: `archivebox` uses `abx-dl` to install plugin binaries, run snapshot downloads, and handle plugin-facing runtime work.
- Boundary: `archivebox` should never know about individual plugins or their resources such as Chrome, and it should not re-implement functionality that already belongs in `abx-dl`.
- Runtime model: `archivebox` listens to the `abx-dl` event stream, projects events into its database, and injects events back to steer `abx-dl`. `abx-dl` owns the actual orchestration runtime for snapshot execution and installs.
