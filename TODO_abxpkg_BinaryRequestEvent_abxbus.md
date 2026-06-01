# TODO: Move BinaryRequest resolution into abxpkg via abxbus

## Goal

Move binprovider resolution out of `abx-plugins` and into `abxpkg`, while keeping the existing ArchiveBox / `abx-dl` install lifecycle intact.

The end state should be:

```text
ArchiveBox / abx-dl
  emits BinaryRequestEvent
        |
        v
abxpkg BinaryService
  resolves / loads / installs the requested binary using native abxpkg providers
        |
        v
ArchiveBox / abx-dl
  receives BinaryEvent
  updates install cache, derived config, Binary DB rows, and UI state
```

This should let us remove user-facing binprovider plugins like `env`, `pip`, `npm`, `apt`, `brew`, `cargo`, `bash`, `puppeteer`, `playwright`, and `chromewebstore` from `abx-plugins` without losing preflight installs, binary DB projection, or config-driven dependency declarations.

## Current State

`abx-dl` currently owns the bus lifecycle:

- `InstallEvent` reads enabled plugin `config.json > required_binaries`.
- Each hydrated dependency becomes a `BinaryRequestEvent`.
- `BinaryService` handles `BinaryRequestEvent`.
- It dispatches provider hooks from `abx-plugins`, e.g. `on_BinaryRequest__10_npm.py`.
- Those provider hooks are wrappers around abxpkg providers.
- Provider hook stdout emits JSONL `{"type": "Binary", ...}` records.
- `abx-dl` converts those records into `BinaryEvent`.
- ArchiveBox listens to the same events and persists DB state.

This works, but it makes provider mechanisms appear as first-class ArchiveBox / `abx-dl` plugins. That clutters plugin lists and duplicates logic already native to `abxpkg`.

## Desired Ownership

`abxpkg` should own:

- provider registry and provider ordering
- binary load / install behavior
- provider-specific install roots and env construction
- version detection
- checksum / metadata when available
- provider locking / dedupe if needed
- normalized `BinaryEvent` emission

`abx-dl` should own:

- reading plugin `config.json`
- hydrating dynamic `required_binaries` using runtime config
- deciding whether auto-install is enabled
- emitting `BinaryRequestEvent` during install preflight
- waiting on install completion
- install cache / derived config updates if those remain `abx-dl` concepts

ArchiveBox should own:

- DB projection into `Binary`, `Machine`, `Process`, etc.
- UI state
- any ArchiveBox-specific policy around install timing or failure handling

`abxpkg` must not import ArchiveBox models, Django settings, snapshots, crawls, or plugin config types.

## Event Boundary

Use events for writes and side effects, not pure reads.

Good event usage:

- `BinaryRequestEvent`: command/request to resolve, load, or install a binary.
- `BinaryEvent`: result of a load/install side effect.
- optional log/progress events if abxbus has a generic convention for them.

Avoid event usage for:

- asking for static provider lists
- asking whether a provider exists
- reading a local cache in a way that can be a normal method call
- pure metadata lookup that has no side effect

## Proposed Generic Event Shape

The first implementation can either define these event classes in `abxpkg`, or accept compatible event classes from callers by duck-typing fields. Prefer explicit abxpkg event classes if that matches latest `abxbus` patterns.

Input:

```python
class BinaryRequestEvent(BaseEvent):
    name: str
    binproviders: str | list[str] = "env"
    min_version: str = ""
    overrides: dict[str, Any] = {}
    install_root: str | None = None
    env: dict[str, str] = {}
    binary_id: str = ""
    plugin_name: str = ""
    hook_name: str = ""
    machine_id: str = ""
    output_dir: str = ""
    auto_install: bool = True
```

Output:

```python
class BinaryEvent(BaseEvent):
    name: str
    abspath: str
    version: str = ""
    sha256: str = ""
    binproviders: str = ""
    binprovider: str = ""
    overrides: dict[str, Any] = {}
    binary_id: str = ""
    plugin_name: str = ""
    hook_name: str = ""
    machine_id: str = ""
    status: str = "loaded"  # or "installed" / "failed" if we standardize this
```

Keep field names compatible with existing `abx-dl.events.BinaryRequestEvent` and `BinaryEvent` as much as possible so `abx-dl` can adopt this with minimal glue.

## Proposed abxpkg API

Add an abxbus service to `abxpkg`, for example:

```text
abxpkg/events.py
abxpkg/services.py
```

or a similarly small, obvious module name.

Main service:

```python
class BinaryService:
    LISTENS_TO = [BinaryRequestEvent]
    EMITS = [BinaryEvent]

    def __init__(self, bus: EventBus, *, auto_install: bool = True, install_root: Path | None = None):
        self.bus = bus
        self.auto_install = auto_install
        self.install_root = install_root
        self.bus.on(BinaryRequestEvent, self.on_BinaryRequestEvent)
```

The handler should:

1. Normalize provider names from `event.binproviders`.
2. Resolve those provider names through the native abxpkg provider registry.
3. Build an `abxpkg.Binary` using the request fields.
4. Try provider `load()` first when appropriate.
5. If missing and auto-install is enabled, call `install()`.
6. Emit exactly one successful `BinaryEvent` when a binary is resolved.
7. Raise or emit a failed terminal result consistently when resolution fails.

Do not shell out to provider hooks.

## Provider Registry

Create one canonical provider name registry in `abxpkg`.

It should map names like:

```text
env
apt
brew
pip
uv
npm
pnpm
yarn
bun
cargo
bash
puppeteer
playwright
chromewebstore
docker
deno
gem
goget
nix
```

to the existing provider classes.

Avoid duplicating provider selection logic in `abx-dl`.

## Compatibility With Existing abx-dl

Once abxpkg exposes the service, `abx-dl` can replace:

```text
BinaryRequestEvent -> provider plugin hook ProcessEvent -> Binary JSONL -> BinaryEvent
```

with:

```text
BinaryRequestEvent -> abxpkg BinaryService -> BinaryEvent
```

`abx-dl` should still keep:

- `InstallEvent`
- config hydration
- dynamic `{CHROME_BINARY}` / `{YTDLP_BINARY}` interpolation
- install cache pruning
- derived config persistence
- `LIB_BIN_DIR` symlink behavior unless that is intentionally moved later

## What Can Be Removed Later

After `abx-dl` uses the abxpkg service, these provider plugins can stop being real `abx-plugins`:

- `env`
- `pip`
- `npm`
- `apt`
- `brew`
- `cargo`
- `bash`
- `puppeteer`
- `playwright`
- `chromewebstore`

They may be deleted, hidden, or converted to thin compatibility shims temporarily.

## What Should Not Move Yet

Do not move these into abxpkg:

- ArchiveBox DB writes
- ArchiveBox Django models
- ArchiveBox settings
- snapshot / crawl semantics
- plugin enablement policy
- user-facing ArchiveBox config UI
- crawling or extraction hooks

Also do not replace all dependency declarations with hook shebang metadata yet. Shebang metadata is useful for standalone hook execution, but `required_binaries` is still needed for config-driven preflight, UI visibility, derived config, and DB projection.

## Read/Write Rule

Use normal methods for pure reads:

- list providers
- get provider class by name
- inspect provider defaults
- parse binprovider strings
- check static compatibility

Use events for side effects:

- install binary
- load and record binary result
- emit install result
- optionally emit progress logs

## Failure Behavior

Decide whether a failed install should:

- raise from the handler, preserving current abxbus failure behavior, or
- emit a failed `BinaryEvent` and then raise, or
- emit only a failed `BinaryEvent`.

Prefer matching existing `abx-dl` behavior first to avoid changing CLI and UI semantics.

Current `abx-dl` behavior generally returns `None` when no provider succeeds, with missing required binaries handled by the caller. Preserve that unless there is a clear reason to standardize explicit failed `BinaryEvent`s.

## Interruptibility / Idempotency

The service should be safe to rerun:

- loading an already-installed binary should not reinstall it
- installing into an existing managed provider dir should reuse the provider cache
- failed installs should not poison future loads
- interrupted installs should be cleaned up or retried by existing provider behavior

If abxpkg already has provider-level locking, use it. If not, add only minimal locking around shared install roots when a real race is observed.

## Tests

Add focused abxpkg tests first:

1. `BinaryRequestEvent` for an `env` binary emits a `BinaryEvent`.
2. provider order is respected.
3. `auto_install=False` does not install missing binaries.
4. a managed provider request emits `binprovider` correctly.
5. `overrides` propagate into the provider.
6. failures do not emit successful `BinaryEvent`s.
7. service works against latest `abxbus` without requiring `abx-dl`.

Then add integration tests in `abx-dl` after wiring:

1. install preflight still emits required `BinaryRequestEvent`s.
2. `BinaryEvent`s still update derived config.
3. `LIB_BIN_DIR` symlinks still work.
4. provider plugins are not required in `include_providers=True`.
5. plugin list output no longer shows binproviders as user-facing plugins.

## Migration Steps

1. In `abxpkg`, add abxbus dependency if missing.
2. Add generic `BinaryRequestEvent` / `BinaryEvent` only if they do not already exist in latest `abxbus`.
3. Add provider registry helper.
4. Add `BinaryService` that consumes `BinaryRequestEvent` and emits `BinaryEvent`.
5. Add tests in `abxpkg`.
6. In `abx-dl`, replace provider-hook dispatch with abxpkg `BinaryService`.
7. Keep current provider plugins available during transition, but stop loading them by default.
8. Once verified, remove or hide provider plugins from `abx-plugins`.
9. Update docs to describe binproviders as abxpkg providers, not plugins.

## Open Questions

- Should `BinaryRequestEvent` / `BinaryEvent` live in `abxpkg`, `abxbus`, or remain in `abx-dl` with abxpkg accepting compatible classes?
- Should failed installs produce failed `BinaryEvent`s, or should failure stay in abxbus handler results?
- Should `LIB_BIN_DIR` linking remain in `abx-dl`, or should abxpkg expose a generic link-dir option?
- Should install cache remain an `abx-dl` derived config concern, or should abxpkg provide a small generic install cache?
- How much provider progress should be emitted as events versus normal logs?

## Non-Goals

- Do not rewrite the crawl lifecycle.
- Do not remove `required_binaries`.
- Do not make abxpkg depend on ArchiveBox.
- Do not replace Python hook `uv` metadata with abxpkg metadata unless there is a concrete benefit.
- Do not introduce new user-facing provider plugin concepts.
