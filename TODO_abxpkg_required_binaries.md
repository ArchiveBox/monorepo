# TODO: Move `required_binaries` ownership into `abxpkg`

Dry-run implementation notes only. No product code changes were made while collecting this.

Goal:
- make `abxpkg` own the `required_binaries` / script-dependency shape, resolution, install/cache/env behavior
- remove duplicated packaging logic from `abx-dl` and `abx-plugins`
- keep final installed-binary records flowing into `ArchiveBox` DB projection
- do not preserve the whole `BinaryRequest` provider-hook flow unless it is still useful as an internal implementation detail


## High-level target architecture

### `abxpkg`
- Own the canonical dependency schema and parser.
- Reuse the same shape already accepted by `abxpkg run --script` `dependencies = [...]`.
- Expose a Python API that accepts raw dependency records and returns validated `Binary` objects and/or loaded binaries.
- Continue owning:
  - install roots
  - `derived.env`
  - provider-owned dependency caches
  - runtime env merging via `build_exec_env(...)` / `apply_exec_env(...)`

### `abx-dl`
- Stop owning package/install/cache/env-building logic.
- Stop dispatching `BinaryRequestEvent` to plugin install hooks for dependency preflight.
- Instead:
  - load plugin config
  - hand `required_binaries` records directly to `abxpkg`
  - emit final resolved binary records/events
- Keep event emission needed for downstream consumers, especially final installed binary records.

### `abx-plugins`
- Stop owning binary provider plugins (`on_BinaryRequest__*`) and binary request emission helpers.
- Keep normal plugin config loading and crawl/snapshot hook code.
- Reuse `abxpkg` env merge helpers for runtime subprocess envs.

### `ArchiveBox`
- Keep the DB projection of final binary records.
- Stop depending on `BinaryRequestEvent` for correctness if possible.
- If `abx-dl` still emits `BinaryRequestEvent` temporarily, treat it as optional compatibility noise.


## Shared shape to converge on

The right shape to reuse is the same one already accepted by `abxpkg run --script`.

Current `abxpkg` script dependency path:
- `../abxpkg/abxpkg/cli.py:1604-1707`
- Same-name dependency merge logic:
  - `../abxpkg/abxpkg/cli.py:1623-1694`

Current accepted forms already include:
- string shorthand: `"python3"`
- dict with `name`
- optional:
  - `binproviders`
  - `min_version`
  - `postinstall_scripts`
  - `min_release_age`
  - `euid`
  - `install_timeout`
  - `version_timeout`
  - `install_root`
  - `bin_dir`
  - `overrides`
  - handler-style keys:
    - `abspath`
    - `version`
    - `install_args`
    - `packages`

Current gap:
- the normalization/merging logic for this shape still lives inline in `cli.py`
- it is not yet a reusable base API that `abx-dl` can call directly

Desired `abxpkg` end state:
- one shared parser/normalizer for:
  - `run --script` dependencies
  - plugin `required_binaries`
- likely output:
  - `list[Binary]`
  - or `list[BinaryOptions]` then `Binary.model_validate(...)`


## Relevant code paths

### Repo: `../abxpkg`

#### 1. Script dependency parsing and merging
- `../abxpkg/abxpkg/cli.py:1564-1707`

Key snippet:

```py
for dep in meta.get("dependencies", []):
    if isinstance(dep, str):
        dep_name = dep
        dep_options = run_options
    elif isinstance(dep, dict):
        ...
        if "binproviders" in dep:
            dep_options = replace(dep_options, provider_names=dep["binproviders"])
        if "min_version" in dep:
            dep_options = replace(dep_options, min_version=dep["min_version"])
    ...
```

And same-name merge:

```py
if dep_name == binary_name:
    ...
    for field_name in (
        "min_version",
        "postinstall_scripts",
        "min_release_age",
        "euid",
        "install_timeout",
        "version_timeout",
    ):
        ...
```

This is the logic that should become the shared dependency-shape parser instead of staying CLI-only.

#### 2. Shared runtime env merge path
- `../abxpkg/abxpkg/config.py:29-117`

Important functions:
- `apply_exec_env(...)`
- `merge_exec_path(...)`
- `build_exec_env(...)`

This is already the correct shared env behavior to reuse in:
- `abxpkg`
- `abx-dl`
- `abx-plugins`

#### 3. Canonical `Binary` shape
- `../abxpkg/abxpkg/binary.py:45-180`

Important fields:
- `name`
- `binproviders`
- `overrides`
- `min_version`
- `postinstall_scripts`
- `min_release_age`

This is the model that `required_binaries` should converge to.

#### 4. Provider-owned cache/env state
- `../abxpkg/abxpkg/binprovider.py`
- `../abxpkg/abxpkg/binprovider.py:415-816`
- `../abxpkg/abxpkg/binprovider.py:1298-1436`

Important facts:
- `derived_env_path` is provider-owned
- cache lives in provider roots
- `depends_on_binaries()` / `installed_binaries()` now live on base `BinProvider`

This supports the user’s desired direction: `abxpkg` already owns most package/install state.


### Repo: `../abx-dl`

#### 1. Duplicate dependency-preflight orchestration
- `../abx-dl/abx_dl/services/binary_service.py:53-200`

Current behavior:

```py
LISTENS_TO = [InstallEvent, ProcessStdoutEvent, BinaryRequestEvent, BinaryEvent]
...
self.binary_hooks = sorted(
    [(plugin, hook) for plugin in plugins.values() for hook in plugin.filter_hooks("BinaryRequest")]
)
...
self.bus.on(BinaryRequestEvent, on_BinaryRequest)
```

This is the install-provider plugin fanout that should largely go away.

#### 2. `InstallEvent -> required_binaries -> BinaryRequestEvent`
- `../abx-dl/abx_dl/services/binary_service.py:202-282`

Key snippet:

```py
for record in get_required_binary_requests(...):
    request_event = BinaryRequestEvent(...)
    await self.bus.emit(request_event)
```

This should become:
- `required_binaries -> abxpkg Binary/load_or_install -> BinaryEvent`

#### 3. Duplicate derived cache ownership
- `../abx-dl/abx_dl/services/binary_service.py:329-415`
- `../abx-dl/abx_dl/services/binary_service.py:460-515`

Current duplicate state:
- `_iter_cached_binary_candidates(...)`
- `_emit_cached_binary_if_already_installed(...)`
- `_persist_binary_abspath_in_config(...)`
- `ABX_INSTALL_CACHE`
- `_link_installed_binary(...)`

This is the core packaging/cache logic that should be removed.

#### 4. Duplicate `required_binaries` model
- `../abx-dl/abx_dl/models.py:79-88`

```py
class RequiredBinary(BaseModel):
    name: str
    binproviders: str = "env"
    min_version: str | None = None
    overrides: BinaryOverrides = Field(default_factory=dict)
```

This should disappear or become a thin alias to the shared `abxpkg` dependency schema.

#### 5. Duplicate runtime env assembly
- `../abx-dl/abx_dl/models.py:195-250`

Current behavior in `PluginEnv.to_env()`:
- scans `*_BINARY`
- prepends `LIB_BIN_DIR`
- prepends `PIP_BIN_DIR`
- prepends `NPM_BIN_DIR`
- prepends `sys.executable` dir
- special-cases `UV`

This should be removed or drastically simplified. Runtime subprocess env should come from resolved `abxpkg` provider env, not reconstructed by `abx-dl`.

#### 6. Duplicate config/derived state ownership
- `../abx-dl/abx_dl/config.py:414-455`
- `../abx-dl/abx_dl/config.py:458-494`

Current state:
- `get_derived_config()`
- `set_derived_config()`
- `unset_derived_config()`
- `LIB_BIN_DIR`
- `PIP_BIN_DIR`
- `NPM_BIN_DIR`
- `ABX_INSTALL_CACHE`

This is a major duplicate ownership layer that should be removed or minimized.

#### 7. `required_binaries` hydration helper
- `../abx-dl/abx_dl/config.py:507-535`

Current behavior:

```py
plugin_config = _load_plugin_config_model(...)
env = PluginEnv.from_config(...).to_env()
for spec in binaries:
    record = spec.model_dump(mode="json")
    record["name"] = spec.name.format(**env)
```

This is the current seam to replace with a shared `abxpkg` parser/hydrator.

#### 8. Docs explicitly describe the old ownership
- `../abx-dl/README.md:45-47`
- `../abx-dl/README.md:54-99`
- `../abx-dl/README.md:191-191`

The README still documents:
- `BinaryRequestEvent`
- `derived.env`
- `ABX_INSTALL_CACHE`
- `*_BINARY` cache reuse

All of that would need updating once the migration lands.


### Repo: `../abx-plugins`

#### 1. Binary provider plugin hooks to remove

Current provider hooks:
- `../abx-plugins/abx_plugins/plugins/env/on_BinaryRequest__00_env.py`
- `../abx-plugins/abx_plugins/plugins/npm/on_BinaryRequest__10_npm.py`
- `../abx-plugins/abx_plugins/plugins/pip/on_BinaryRequest__11_pip.py`
- `../abx-plugins/abx_plugins/plugins/brew/on_BinaryRequest__12_brew.py`
- `../abx-plugins/abx_plugins/plugins/cargo/on_BinaryRequest__12_cargo.py`
- `../abx-plugins/abx_plugins/plugins/puppeteer/on_BinaryRequest__12_puppeteer.py`
- `../abx-plugins/abx_plugins/plugins/apt/on_BinaryRequest__13_apt.py`
- `../abx-plugins/abx_plugins/plugins/bash/on_BinaryRequest__14_bash.py`
- `../abx-plugins/abx_plugins/plugins/chromewebstore/on_BinaryRequest__90_chromewebstore.py`

These are the primary install/provider hooks to delete once `abxpkg` owns resolution/install.

#### 2. Plugin config loader still owns `required_binaries` validation
- `../abx-plugins/abx_plugins/plugins/base/utils.py:40-61`

```py
class ConfigSchemaDocument(BaseModel):
    required_binaries: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("required_binaries", mode="before")
    def validate_required_binaries(...)
```

This is currently a very shallow validation step. Long-term, `abxpkg` should own the real parsing/validation.

#### 3. JSONL emission helpers tied to BinaryRequest/Binary flow
- `../abx-plugins/abx_plugins/plugins/base/utils.py:575-610`

Current helpers:
- `emit_binary_request_record(...)`
- `emit_installed_binary_record(...)`

If `BinaryRequest` goes away, this layer should shrink.

#### 4. Plugin README documents the old BinaryRequest contract
- `../abx-plugins/README.md:24-29`
- `../abx-plugins/README.md:48-93`

It currently documents:
- `required_binaries`
- `on_BinaryRequest__*`
- `BinaryRequest -> Binary`
- provider hook responsibility
- standalone `derived.env`

This will need a broad rewrite once ownership moves.


### Repo: `../ArchiveBox`

#### 1. DB projection currently listens to both request + installed events
- `../ArchiveBox/archivebox/services/binary_service.py:9-16`

```py
LISTENS_TO = [BinaryRequestEvent, BinaryEvent]
...
self.bus.on(BinaryRequestEvent, self.on_BinaryRequestEvent)
self.bus.on(BinaryEvent, self.on_BinaryEvent)
```

This is the main downstream dependency on the old flow.

#### 2. Request projection currently creates/updates queued DB rows
- `../ArchiveBox/archivebox/services/binary_service.py:18-75`

Current effect:
- on `BinaryRequestEvent`:
  - create/update `machine_binary` row with `status=QUEUED`
  - if an installed DB row already exists, emit synthetic `BinaryEvent`

This is not necessarily needed if final installed records are the only thing that matters.

#### 3. Final installed projection is already separate
- `../ArchiveBox/archivebox/services/binary_service.py:77-103`

Current effect:
- on `BinaryEvent`:
  - update/create `machine_binary`
  - populate `abspath`, `version`, `sha256`, `binprovider`
  - mark `status=INSTALLED`

This is the part we definitely need to keep.

#### 4. Process typing still assumes `on_BinaryRequest`
- `../ArchiveBox/archivebox/services/process_service.py:39-41`
- `../ArchiveBox/archivebox/services/process_service.py:98-100`

```py
Process.TypeChoices.BINARY if event.hook_name.startswith("on_BinaryRequest") else Process.TypeChoices.HOOK
```

If provider hooks disappear, this logic must change or become irrelevant.

#### 5. ArchiveBox runner currently explicitly emits `BinaryRequestEvent`
- `../ArchiveBox/archivebox/services/runner.py:549-583`

Key snippet:

```py
await bus.emit(
    BinaryRequestEvent(
        name=binary.name,
        ...
        binproviders=binary.binproviders,
        overrides=binary.overrides or None,
    ),
)
```

This is the exact call site that should become a direct `abxpkg` resolution/install API call if ArchiveBox stops using the old flow.

#### 6. ArchiveBox `Binary` machine model still owns provider-hook execution
- `../ArchiveBox/archivebox/machine/models.py:573-669`

Current behavior:
- discovers all `on_BinaryRequest__*` hooks
- runs them one by one
- first successful `Binary` record wins
- links into `LIB_BIN_DIR`

This entire `Binary.run()` path becomes redundant if `abxpkg` takes over install resolution.

#### 7. ArchiveBox still owns LIB_BIN_DIR symlink behavior
- `../ArchiveBox/archivebox/machine/models.py:685-720`

`Binary.symlink_to_lib_bin(...)` is part of the old shared-bin-dir ownership. This becomes suspect if `abxpkg` already owns symlink/cached install state.


## What to remove vs keep

### Remove from `abx-dl`
- `ABX_INSTALL_CACHE`
- `derived.env` packaging cache ownership
- `*_BINARY` derived persistence for installed binary paths
- `LIB_BIN_DIR` symlink maintenance
- `BinaryRequestEvent` preflight fanout to provider plugins
- `RequiredBinary` as a separate schema/model
- `PluginEnv.to_env()` package PATH assembly from:
  - `*_BINARY`
  - `LIB_BIN_DIR`
  - `PIP_BIN_DIR`
  - `NPM_BIN_DIR`
  - `sys.executable`

### Remove from `abx-plugins`
- `on_BinaryRequest__*` provider plugins
- `emit_binary_request_record(...)`
- docs/tests that assert BinaryRequest plugin behavior
- provider-specific packaging/install logic for env/pip/npm/brew/etc.

### Keep in `abx-dl`
- final binary records/events
- whatever event shape is needed for ArchiveBox projection
- plugin config loading
- crawl/snapshot hook orchestration

### Keep in `ArchiveBox`
- final `BinaryEvent -> DB` projection
- machine `Binary` rows in DB
- any UI/admin/reporting that reads final installed binaries

### Probably remove or radically simplify in `ArchiveBox`
- `BinaryRequestEvent -> DB queued row` projection
- `archivebox.machine.Binary.run()` hook-execution installer path
- `LIB_BIN_DIR` symlink ownership for installed binaries
- process-type detection that assumes `on_BinaryRequest__*`


## Recommended implementation plan

### Phase 1: Centralize the schema in `abxpkg`
1. Extract the current `run --script` dependency normalization from `../abxpkg/abxpkg/cli.py:1604-1694` into a shared `abxpkg` API.
2. Make it accept:
   - `list[str | dict[str, Any]]`
3. Make it output:
   - validated `Binary` objects
   - or a typed intermediate shape that becomes `Binary`
4. Reuse that same parser in `run --script`.

Result:
- one dependency/required-binary schema across all repos

### Phase 2: Switch `abx-dl` to direct `abxpkg` resolution
1. Replace `get_required_binary_requests(...)` + `BinaryRequestEvent` emission with:
   - `abxpkg` parser
   - `Binary(...).load()` / `.install()` / equivalent direct resolution
2. Convert final resolved binaries into `BinaryEvent` (or successor event) records on the bus.
3. Delete:
   - `ABX_INSTALL_CACHE`
   - `_iter_cached_binary_candidates(...)`
   - `_emit_cached_binary_if_already_installed(...)`
   - `_persist_binary_abspath_in_config(...)`
   - `_link_installed_binary(...)`

Result:
- `abx-dl` no longer owns packaging/cache state

### Phase 3: Remove provider plugins from `abx-plugins`
1. Delete `on_BinaryRequest__*` provider plugins.
2. Remove BinaryRequest docs/helpers/tests.
3. Keep:
   - `config.json`
   - normal snapshot/crawl hooks
4. Keep `required_binaries` in plugin config, but make it just data for `abxpkg`.

Result:
- `abx-plugins` stops owning install/provider behavior

### Phase 4: Simplify runtime env assembly
1. Make `abx-dl` subprocess env assembly use `abxpkg.config.build_exec_env(...)` from resolved binaries/providers.
2. Remove package PATH ownership from `PluginEnv.to_env()`.
3. Keep only general non-package env in `PluginEnv`.

Result:
- one runtime env merge path everywhere

### Phase 5: Simplify ArchiveBox projection
1. Keep `BinaryEvent -> DB` projection.
2. Decide whether to:
   - remove `BinaryRequestEvent -> DB queued row`
   - or keep it temporarily as optional compatibility
3. Replace any runner path that currently emits `BinaryRequestEvent` with direct `abxpkg` resolution plus final emitted installed records.

Result:
- ArchiveBox only cares about final binary state, not provider orchestration internals


## Remaining ambiguities / complexities to resolve

### 1. What exact API should `abxpkg` expose?
Open question:
- should it return `list[Binary]`
- or expose a higher-level helper like:
  - `resolve_required_binaries(...)`
  - `load_or_install_required_binaries(...)`

Constraint:
- do not invent unnecessary new layers
- but `abx-dl` needs a clean batch entry point

Most likely:
- one parser for dependency records
- one small batch resolver that returns loaded binaries

### 2. How much of `BinaryRequestEvent` should survive?
User explicitly said:
- only final installed records matter
- do not care about preserving the whole BinaryRequest flow

Open question:
- should `BinaryRequestEvent` disappear entirely
- or remain as an internal/compatibility event for a transition period

Recommendation:
- treat it as transitional at most
- do not make the new architecture depend on it

### 3. ArchiveBox queued binary rows
Current ArchiveBox behavior creates queued `machine_binary` rows from `BinaryRequestEvent`.

Open question:
- is it acceptable to only create/update rows on final installed events
- or does ArchiveBox UI/state-machine logic still need queued rows

User guidance so far suggests:
- final installed records matter more than preserving queued-request projection

Need a deliberate decision before deleting that path.

### 4. What happens to machine config derived binary keys?
Current `abx-dl` and ArchiveBox both persist config-ish data representing resolved binaries:
- `*_BINARY` in `derived.env`
- equivalent machine config/DB state

If `abxpkg` owns install/cache state:
- should machine config stop storing resolved paths entirely
- or should final `BinaryEvent`s still write some derived compatibility keys

Recommendation:
- do not persist derived path config unless a non-install consumer truly needs it
- prefer final binary rows/events only

### 5. `LIB_DIR` default alignment
Current mismatch:
- `abxpkg`: `~/.config/abx/lib`
- `abx-dl`: `~/.config/abx/lib/<arch>`

Need a hard decision:
- standardize `abx-dl` / ArchiveBox onto the `abxpkg` default

Recommendation:
- yes, standardize on `abxpkg`’s default
- only one `ABXPKG_LIB_DIR`

### 6. How much plugin config loading should move?
`abx-plugins base/utils.py` currently does:
- schema loading
- alias/fallback resolution
- `required_binaries` shallow validation

Open question:
- should `abxpkg` also load plugin config files directly
- or just accept already-hydrated `required_binaries`

Recommendation:
- keep plugin config loading in `abx-plugins`
- move only `required_binaries` parsing/validation/install semantics into `abxpkg`

### 7. How should runtime env be built from final binaries?
`build_exec_env(...)` currently works from providers, not from a list of final `BinaryEvent` bus records.

Need a concrete bridge:
- `BinaryEvent` -> provider instance list -> `build_exec_env(...)`

Open question:
- do we reconstruct providers from `BinaryEvent.binprovider`
- or do we retain the resolved provider objects alongside the emitted events inside `abx-dl`

Recommendation:
- keep actual loaded `abxpkg` binaries/provider instances in memory during one run
- emit final `BinaryEvent`s for projection
- build subprocess env from the real loaded objects, not from DB/event reconstruction


## Practical repo-by-repo edit list when implementation starts

### `../abxpkg`
- move script dependency normalization out of CLI and into shared API
- document the shared dependency shape if needed

### `../abx-dl`
- replace `BinaryService` preflight provider-hook pipeline with direct `abxpkg` calls
- delete derived binary cache logic and `ABX_INSTALL_CACHE`
- simplify `PluginEnv.to_env()`
- align `ABXPKG_LIB_DIR`
- update docs/tests

### `../abx-plugins`
- delete provider/install plugins
- delete BinaryRequest docs/helpers/tests
- keep plugin config files and non-provider hooks

### `../ArchiveBox`
- replace direct `BinaryRequestEvent` emission in runner paths
- keep final `BinaryEvent` DB projection
- simplify/remove `archivebox.machine.Binary.run()`
- remove shared-bin-dir ownership if no longer needed


## Proposed order of attack

1. `abxpkg`: shared parser/normalizer for dependency records
2. `abx-dl`: use shared parser + direct `abxpkg` resolution, emit final binary records
3. `ArchiveBox`: consume final binary records only, trim request-path assumptions
4. `abx-plugins`: delete provider plugins and BinaryRequest-specific docs/tests

That order minimizes breakage because:
- `abxpkg` becomes the source of truth first
- `abx-dl` can switch next
- `ArchiveBox` can keep projecting final binary state throughout
- `abx-plugins` can be simplified last once nothing depends on provider hooks anymore
