# TODO: Machine Config Refactor

codex resume 'refactor Machine config modification to use a seaprate
ConfigKeyValue model with append-only events'

## Goal

Replace `Machine.config` as a `JSONField` on `Machine` with a separate normalized model, while preserving 
the existing Python-level `machine.config` API for current callers.
Proposed new model shape:

```py
class ConfigKeyValue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, null=False)
    key = models.CharField(max_length=..., null=False)
    value = models.JSONField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
```

The read-side compatibility target is:

- `machine.config` still returns a `dict[str, Any]`
- existing read sites do not need to care that storage moved
- write sites switch to explicit helpers instead of mutating a DB field directly


## Main Findings

- `Machine.config` is only read in a few real runtime places:
  - `archivebox/archivebox/machine/models.py`
  - `archivebox/archivebox/services/runner.py`
  - `archivebox/archivebox/core/views.py`
- `Machine.config` is **not** part of the main `get_config()` merge path in `archivebox/archivebox/config/configset.py`. The main config merge uses persona/user/crawl/snapshot config, not machine config.
- The current ArchiveBox DB persistence is already inconsistent:
  - `archivebox/archivebox/services/machine_service.py` ignores `config_type`, so it persists both `"user"` and `"derived"` events into `Machine.config`
  - it also ignores `"unset"`, so stale config keys are never removed from DB today
- `Machine.from_json()` appears to be effectively dead outside tests.
- A `@property` getter is not enough by itself:
  - callers also write with `machine.config = ...`
  - there are `save(update_fields=["config"])` callsites
  - Django admin currently assumes `config` is a real model field


## Relevant Files

### ArchiveBox

- `archivebox/archivebox/machine/models.py`
- `archivebox/archivebox/services/machine_service.py`
- `archivebox/archivebox/services/runner.py`
- `archivebox/archivebox/core/views.py`
- `archivebox/archivebox/machine/admin.py`
- `archivebox/archivebox/base_models/admin.py`
- `archivebox/archivebox/cli/archivebox_machine.py`
- `archivebox/archivebox/tests/test_machine_models.py`
- `archivebox/archivebox/tests/test_runner.py`
- `archivebox/archivebox/tests/test_config_views.py`
- `archivebox/archivebox/misc/jsonl.py`
- `archivebox/archivebox/config/configset.py`
- `archivebox/archivebox/machine/migrations/0001_initial.py`
- `archivebox/archivebox/machine/migrations/0011_remove_binary_output_dir.py`

### abx-dl / event flow

- `abx-dl/abx_dl/events.py`
- `abx-dl/abx_dl/config.py`
- `abx-dl/abx_dl/services/binary_service.py`
- `abx-dl/abx_dl/services/machine_service.py`
- `abx-dl/abx_dl/orchestrator.py`
- `abx-dl/tests/test_executor.py`
- `abx-dl/tests/test_install_phase.py`
- `abx-dl/tests/test_config.py`


## Current Behavior Notes

### Machine storage today

`Machine` currently stores:

- hardware / OS metadata
- `stats`
- `config` as a JSON blob

Current implementation is in `archivebox/archivebox/machine/models.py`.

Important methods:

- `Machine.current()`
- `Machine._sanitize_config()`
- `Machine.to_json()`
- `Machine.from_json()`
- `_sanitize_machine_config()`

Current write behavior:

- `Machine.current()` sanitizes and may save back to DB
- `Machine.from_json()` merges a config patch and saves back to DB
- `archivebox.services.machine_service.MachineService` merges runtime `MachineEvent` config into `machine.config`

### Live config UI today

`archivebox/archivebox/core/views.py` checks `Machine.current().config` in:

- `find_config_source()`
- `live_config_value_view()`

This is only for display / provenance. It is not part of the normal config merge path.

### Runner behavior today

`archivebox/archivebox/services/runner.py` reads:

- `dict(Machine.current().config)` for crawl runs
- `dict(machine.config)` for binary/install runs

This is used as `derived_config_overrides` for `abx-dl`.

### Event behavior today

`abx-dl` currently uses `MachineEvent` in two different ways:

1. bulk seed:
   - `MachineEvent(config=..., config_type="user")`
   - `MachineEvent(config=..., config_type="derived")`
2. incremental mutation:
   - `MachineEvent(method="update", key="config/FOO", value=..., config_type="derived")`
   - `MachineEvent(method="unset", key="config/FOO", config_type="derived")`

The `"config/KEY"` shape is the hacky part to remove later if desired.


## Caveats

### 1. A property getter alone is not enough

If `Machine.config` stops being a real field, the following current behavior breaks unless replaced:

- `machine.config = {...}`
- `save(update_fields=["config"])`
- admin `fieldsets = ("config",)`
- `ConfigEditorMixin.formfield_for_dbfield()`

Any implementation must add explicit write helpers and update current write callsites.

### 2. Async access risk

Be careful with a `config` property that does fresh ORM reads.

Current async code does things like:

- `machine = await sync_to_async(Machine.current, thread_sensitive=True)()`
- then later `dict(machine.config)`

If the property performs a sync DB query there, it can raise `SynchronousOnlyOperation`.

Safe options:

- hydrate config in sync code before returning the model instance
- or force async callsites to use sync-wrapped helper methods
- or attach prefetched/annotated data to the instance before async callers read it

### 3. Admin is not free

Current admin code assumes `config` is a real DB field:

- `archivebox/archivebox/machine/admin.py`
- `archivebox/archivebox/base_models/admin.py`

If `config` becomes a property:

- `ConfigEditorMixin` will no longer automatically wire up the widget
- `MachineAdmin.fieldsets` cannot simply reference a non-field property unless replaced with custom form logic or readonly rendering

### 4. Current DB semantics already mix user and derived config

ArchiveBox currently persists both `"user"` and `"derived"` `MachineEvent` payloads into `Machine.config` because its `MachineService` ignores `config_type`.

That means a refactor must decide whether to:

- preserve the current mixed semantics
- or intentionally change behavior so only derived cache is stored in DB

Preserving current behavior is simpler and safer for the first pass.

### 5. Current DB semantics ignore unset

ArchiveBox currently does not delete keys from DB when `abx-dl` emits `method="unset"`.

A normalized table makes delete/unset support much easier, but that is still a behavior change and should be called out.

### 6. The queryset annotation is useful, but not sufficient

`JSONObjectAgg(json_group_object(...))` is useful for bulk list/queryset reads.

It is not sufficient by itself because many current callsites operate on ordinary `Machine` instances, not annotated querysets.

Recommended usage:

- use Python dict assembly for the model property / instance helper
- use `JSONObjectAgg` for list endpoints or bulk serialization paths

### 7. Do not implement writes as blind delete + recreate

If `ConfigKeyValue` tracks:

- `created_by`
- `created_at`
- `modified_at`

then normal updates should do a diff:

- create missing keys
- update changed keys
- delete removed keys only when doing replace/unset semantics

Blind delete/recreate would lose row identity and timestamps.

### 8. `Machine.from_json()` is probably not production-critical

I could not find a production callsite for `Machine.from_json()`.

That makes it safe to keep for compatibility or simplify aggressively, but tests currently cover it.


## Proposed Implementation Plan

### Phase 1: Add normalized storage without removing old column

1. Add `ConfigKeyValue` model in `archivebox/archivebox/machine/models.py`.
2. Give it:
   - `id`
   - `machine`
   - `key`
   - `value`
   - `created_by`
   - `created_at`
   - `modified_at`
3. Add migration dependencies for `AUTH_USER_MODEL` if needed.
4. Create the DB table in a new machine migration.
5. Backfill rows from existing `machine_machine.config` JSON blobs.
6. Keep the old `machine_machine.config` column for now.

Notes:

- The machine app’s initial migration is raw-SQL-heavy, so a follow-up migration may need `SeparateDatabaseAndState` or hand-authored SQL depending on how consistent you want it with the existing style.
- Since `created_by` points at auth users, migration dependencies need to be checked carefully.

### Phase 2: Add compatibility helpers on `Machine`

In `archivebox/archivebox/machine/models.py`:

1. Replace direct dependence on the DB field with helpers:
   - `get_config_dict()`
   - `set_config_dict(...)` or `replace_config_dict(...)`
   - `apply_config_patch(...)`
   - `unset_config_keys(...)`
2. Keep `Machine.config` as a compatibility property returning a dict.
3. Optionally support `Machine.config = {...}` via a setter that stages data in memory or writes through.
4. Move sanitizing of legacy keys into helper logic so all code paths share it.

Recommended property behavior:

- if prefetched rows are present, build from them
- otherwise query `configkeyvalue_set.values_list("key", "value")`
- sanitize legacy keys before returning

Avoid doing a self-aggregate query with `json_group_object` inside the property itself.

### Phase 3: Switch ArchiveBox write paths

Update the current write sites to use explicit helpers instead of mutating a JSONField:

- `Machine._sanitize_config()`
- `Machine.from_json()`
- `archivebox/archivebox/services/machine_service.py`
- tests that do `machine.config = {...}` then `save(update_fields=["config"])`

Target behavior:

- bulk config patch writes become helper calls
- unset/delete becomes first-class
- no remaining ArchiveBox code depends on `save(update_fields=["config"])`

### Phase 4: Fix admin

Current admin implementation:

- `MachineAdmin.fieldsets` includes `"config"`
- `ConfigEditorMixin` only works for a real DB field named `config`

Options:

#### Option A: Simple admin

- remove `config` from the Machine form fieldset
- register `ConfigKeyValue` as its own model/admin
- show related config rows inline or via changelist link

This is the simplest and lowest-risk option.

#### Option B: Compatibility admin

- keep an editable synthetic `config` field via custom `ModelForm`
- wire `KeyValueWidget` onto that form field manually
- load initial data from `Machine.config`
- on save, call the explicit config helpers

This preserves the current UX better, but is more work.

### Phase 5: Bulk read optimization

If list/queryset performance matters:

1. Add a custom aggregate wrapper such as `JSONObjectAgg`.
2. Add a queryset/manager helper that annotates `config` from `ConfigKeyValue`.
3. Use it in places like:
   - machine list APIs
   - JSONL export paths
   - any bulk machine listing

This is optional for the first implementation.

### Phase 6: Remove old JSON column

Only after all reads/writes/admin/tests are switched:

1. add a migration removing `Machine.config` from model state
2. remove the physical column from `machine_machine`
3. remove any remaining compatibility shims that assume the DB field exists


## abx-dl Event Refactor Plan

This is optional and should be treated as a separate phase.

### Current ugly part

Incremental runtime config mutation uses:

```py
MachineEvent(method="update", key="config/FOO", value=..., config_type="derived")
MachineEvent(method="unset", key="config/FOO", config_type="derived")
```

This logic currently lives in:

- `abx-dl/abx_dl/services/binary_service.py`
- `abx-dl/abx_dl/config.py`
- `abx-dl/abx_dl/services/machine_service.py`
- `archivebox/archivebox/services/machine_service.py`

### If we want to clean this up later

Introduce a first-class event/record shape for config entries, for example:

- extend `MachineEvent` with explicit `entries`
- or add a dedicated `ConfigKeyValueEvent`
- or emit JSONL `{"type": "ConfigKeyValue", ...}` records if the goal is subprocess-visible records

Then update:

- `abx-dl/abx_dl/config.py` reducers
- `abx-dl/abx_dl/services/binary_service.py` emit sites
- `abx-dl/abx_dl/services/machine_service.py`
- `archivebox/archivebox/services/machine_service.py`

Important note:

- today the `config/KEY` mutations are internal bus events, not stdout hook JSONL records
- switching to real emitted records is a broader protocol change than just changing storage


## Exact Files That Need Changes

### Must change for the storage refactor

- `archivebox/archivebox/machine/models.py`
- `archivebox/archivebox/services/machine_service.py`
- `archivebox/archivebox/machine/admin.py`
- `archivebox/archivebox/base_models/admin.py`
- `archivebox/archivebox/tests/test_machine_models.py`
- `archivebox/archivebox/tests/test_runner.py`
- `archivebox/archivebox/machine/migrations/<new migration>.py`

### Likely change

- `archivebox/archivebox/core/views.py`
- `archivebox/archivebox/cli/archivebox_machine.py`
- `archivebox/archivebox/tests/test_config_views.py`

### Optional later event cleanup

- `abx-dl/abx_dl/events.py`
- `abx-dl/abx_dl/config.py`
- `abx-dl/abx_dl/services/binary_service.py`
- `abx-dl/abx_dl/services/machine_service.py`
- `abx-dl/abx_dl/orchestrator.py`
- `abx-dl/tests/test_executor.py`
- `abx-dl/tests/test_install_phase.py`
- `abx-dl/tests/test_config.py`


## Specific Code Paths To Revisit

### Machine model

In `archivebox/archivebox/machine/models.py`:

- `LEGACY_MACHINE_CONFIG_KEYS`
- `_sanitize_machine_config()`
- `Machine.current()`
- `Machine._sanitize_config()`
- `Machine.to_json()`
- `Machine.from_json()`

### ArchiveBox persistence

In `archivebox/archivebox/services/machine_service.py`:

- current behavior merges full config dict
- current behavior handles `"update"` only
- current behavior ignores `"unset"`
- current behavior ignores `config_type`

### Runner reads

In `archivebox/archivebox/services/runner.py`:

- `load_run_state()`
- `_run_binary()`
- `_run_install()`
- `_emit_machine_config()`

### UI reads

In `archivebox/archivebox/core/views.py`:

- `find_config_source()`
- `live_config_value_view()`

### Tests that directly depend on JSONField semantics

- `archivebox/archivebox/tests/test_machine_models.py`
- `archivebox/archivebox/tests/test_runner.py`


## Migration Notes

### Create-table migration

Need a new migration in `archivebox/archivebox/machine/migrations/`.

It should:

- create `machine_configkeyvalue`
- add FK to `machine_machine`
- add FK to auth user
- store JSON `value`

Potential implementation styles:

- normal Django `CreateModel`
- or `SeparateDatabaseAndState` if you want tighter control over SQL like the existing machine migrations

### Backfill migration

Need a data migration that:

1. iterates existing `Machine` rows
2. loads the old JSON `config`
3. sanitizes legacy keys
4. creates `ConfigKeyValue` rows

Questions to settle during implementation:

- whether to preserve rows for legacy keys before sanitizing
- what `created_by` should be for backfilled rows
  - likely `get_or_create_system_user_pk()`

### Drop-column migration

Do this later, after the refactor is fully switched over.


## Test Plan

### ArchiveBox tests to update/add

#### Update existing

- `archivebox/archivebox/tests/test_machine_models.py`
  - `Machine.from_json()` updates config
  - legacy key stripping
  - `Machine.current()` sanitization

- `archivebox/archivebox/tests/test_runner.py`
  - runner derived config still equals machine config dict

- `archivebox/archivebox/tests/test_config_views.py`
  - machine config still appears as a source in the expected priority ordering

#### Add new

- backfill migration test if practical
- `Machine.config` property returns dict from normalized rows
- helper method tests:
  - patch merge
  - replace
  - unset/delete
  - sanitization
- async-safe read behavior if property hydration strategy is non-trivial

### abx-dl tests to update later if event shape changes

- `abx-dl/tests/test_executor.py`
- `abx-dl/tests/test_install_phase.py`
- `abx-dl/tests/test_config.py`


## Suggested Sequencing

1. Add `ConfigKeyValue` model and migration.
2. Backfill from existing `Machine.config` JSON blobs.
3. Add `Machine` compatibility helpers and property.
4. Switch ArchiveBox write paths off `save(update_fields=["config"])`.
5. Decide and implement admin strategy.
6. Update tests.
7. Remove old JSON column.
8. Separately, clean up the `abx-dl` event shape if still desired.


## Rough Scope Estimate

### Storage refactor only

- medium-sized refactor
- concentrated in a handful of files
- probably a net code increase initially

Estimated rough delta:

- add around `100-180` LOC for normalized storage, helpers, migration, compatibility
- remove/simplify around `60-100` LOC of awkward config plumbing

### If event shape is also cleaned up

- more invasive
- touches both ArchiveBox and `abx-dl`
- improves the architecture more than it reduces total LOC


## Recommendation

Treat this as two separate changes:

1. storage normalization for ArchiveBox `Machine.config`
2. optional bus/event protocol cleanup for `abx-dl`

Doing both at once is possible, but it increases risk and makes regressions harder to isolate.

The storage refactor alone is feasible and reasonably bounded as long as:

- `Machine.config` remains dict-like at the Python level
- writes switch to explicit helper methods
- async property access is handled carefully
- admin is treated as explicit follow-up work, not assumed to keep working automatically
