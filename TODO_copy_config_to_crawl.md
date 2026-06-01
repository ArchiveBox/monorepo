# TODO: Copy Resolved Config Onto Crawl

Goal: store a full resolved runtime config snapshot on every `Crawl.config` at crawl creation time, then use that frozen crawl config for crawl/snapshot/archive-result execution. Runtime behavior should no longer depend on later edits to global, machine, user, or persona defaults.

Raw sensitive values may exist in DB config fields because hooks need them at runtime, but they must never be reflected into crawl-dir JSON/JSONL/log files, REST responses, admin/user-facing HTML, or debug views. Existing redaction behavior using `********` must be preserved.

## Current Config Flow

`archivebox.config.common.get_config()` currently resolves config from many levels on each call:

- explicit overrides
- `ArchiveResult.config`
- `Snapshot.config`
- `Crawl.config`
- `User.config`
- derived `Persona.config`
- `Machine.config`
- environment / config file / plugin defaults / core defaults

The crawl creation paths currently store mostly overrides:

- `/add/`: `archivebox/core/views.py:AddView._create_crawl_from_form`
- CLI add: `archivebox/cli/archivebox_add.py:add`
- REST create: `archivebox/api/v1_crawls.py:create_crawl`
- schedules: `archivebox/crawls/models.py:CrawlSchedule.enqueue`

Execution hot paths repeatedly resolve the full chain:

- `archivebox/services/runner.py:enqueue_pending_snapshots_from_projection`
- `archivebox/services/runner.py:load_run_state`
- `archivebox/services/runner.py:load_snapshot_payload`
- `archivebox/services/runner.py:enqueue_discovered_snapshots_from_outputs`
- `archivebox/crawls/models.py:create_snapshots_from_urls`
- `archivebox/crawls/models.py:create_discovered_snapshots`
- crawl limit helpers and URL filter helpers
- snapshot/archive-result `DELETE_AFTER` helpers

## Target Behavior

At crawl creation time:

- Resolve the full effective config using current machine/env/file/user/persona/default state.
- Overlay explicit crawl form/API/CLI/schedule overrides.
- Store the full resolved raw config in `Crawl.config`.
- Do not mutate `Crawl.config` afterward unless the user explicitly edits it.

During execution:

- `Crawl.config` is the base config for anything below the crawl.
- `Snapshot.config` overlays only snapshot-local overrides.
- `ArchiveResult.config` overlays only result-local overrides.
- Runtime path fields like `CRAWL_DIR`, `SNAP_DIR`, and output dirs are injected at runtime and do not need to be stored permanently.
- Edits to persona/user/machine/global defaults do not affect already-created crawls.
- Edits to `Crawl.config` itself should affect later snapshots/results in that crawl.

In request/UI/server code:

- Continue using request middleware/global config for UI/server concerns like host routing, base URLs, permissions for the current request, admin rendering, and search UI options.
- Evaluate call sites case-by-case. Do not blindly replace all `get_config()` calls with crawl config.

## Redaction Rules

Raw config is allowed in DB fields:

- `Crawl.config`
- `Persona.config`
- `Machine.config`
- `Snapshot.config`
- `ArchiveResult.config`
- runtime hook env / bus events that are only internal to execution

Raw config must not cross outward-facing boundaries:

- REST responses
- admin/user-facing rendered HTML
- `/add/` persona hydration JSON
- live-progress payloads
- crawl/snapshot `index.json`
- crawl/snapshot `index.jsonl`
- exported JSONL
- debug/config views
- copied replay commands
- access logs or process logs shown in UI

Existing redaction paths:

- `archivebox/config/common.py:redact_sensitive_config`
- `archivebox/config/common.py:is_sensitive_config_key`
- `archivebox/base_models/admin.py:ConfigEditorMixin`
- `archivebox/core/forms.py:PluginConfigFormMixin`
- `archivebox/api/v1_crawls.py:CrawlSchema.resolve_config`
- `archivebox/api/v1_personas.py:PersonaSchema.resolve_config`
- `archivebox/crawls/models.py:Crawl.to_json`
- `archivebox/machine/models.py:Machine.to_json`
- `archivebox/machine/env_util.py:redact_env`

Needed cleanup:

- Make `redact_sensitive_config()` the single source of truth for config masking.
- Fold plugin schema `x-sensitive` keys into that central helper.
- Replace `core.views.key_is_safe()` with the central helper/heuristic so config views agree with REST/admin/export behavior.
- Keep the placeholder exactly `********`.
- Preserve write-only form behavior: blank sensitive fields mean “keep current value”, not “clear it”; removing the key means clear it.
- Ensure submitted `********` never overwrites a real stored secret.

## Implementation Plan

1. Add a small central helper for frozen crawl config construction.

   Suggested shape:

   ```python
   def build_crawl_config_snapshot(*, user, persona=None, overrides=None, base_config=None) -> dict[str, Any]:
       effective = get_config(user=user, persona=persona, base_config=base_config)
       frozen = _normalize_runtime_config(effective)
       frozen.update(overrides or {})
       return frozen
   ```

   Keep this close to config/crawl creation code. Avoid a broad abstraction unless multiple creation paths genuinely need it.

2. Update crawl creation paths to store full config.

   - `/add/` builds explicit overrides from form fields, plugin config, filters, permissions, limits, etc., then freezes full config.
   - CLI `archivebox add` does the same.
   - REST crawl creation does the same.
   - Schedule templates should either store frozen config when the schedule is created or freeze when each crawl is enqueued. Prefer freezing when enqueued so scheduled crawls use the defaults current at the time the run starts.

3. Update `get_config()` semantics for crawl-scoped execution.

   Desired behavior:

   - If `crawl` is provided and `crawl.config` is a full frozen config, use it as the base for crawl-scoped config.
   - Do not re-apply current user/persona/machine/env/file defaults underneath it.
   - Still overlay `Snapshot.config`, `ArchiveResult.config`, and explicit overrides.
   - Still inject runtime path values.

   Because existing dev data may contain override-only crawls, either:

   - migrate/backfill existing crawls to full frozen config, then remove compatibility logic, or
   - use a temporary marker only during migration and delete the branch once dev data is clean.

   Prefer migration/backfill and a single final path.

4. Simplify runner and model call sites.

   After crawl config is frozen:

   - `runner.load_run_state()` can use `crawl.config` directly for crawl-level settings.
   - `runner.load_snapshot_payload()` should only add snapshot overlays and runtime dirs.
   - `enqueue_discovered_snapshots_from_outputs()` should use parent snapshot/crawl frozen config.
   - crawl limit helpers should not query persona/user/machine state.
   - expected hook count caching in admin can be simplified because crawl config is already complete.

5. Simplify stale optimization code that exists only because config was dynamic.

   Candidates:

   - `crawls/admin.py:limit_config_for_crawl`
   - `core/admin_snapshots.py:_get_expected_hook_total`
   - `core/views.py` live-progress crawl config hydration
   - `missing_delete_at_candidates()` persona lookups for `DELETE_AFTER`
   - repeated `get_config(crawl=..., include_machine=False)` calls in runner hot paths

6. Keep machine-derived runtime config separate.

   Machine binary discovery state is still special:

   - `Machine.current().config` can be sanitized and used for derived binary/runtime paths.
   - Do not store transient machine cache keys in crawl config if they are not actual runtime settings.
   - `ABX_INSTALL_CACHE`, `CHROME_USER_DATA_DIR`, and similar sanitized machine-only values should stay out of persisted crawl config unless there is a clear runtime need.

7. Harden outward serialization.

   Audit every config-containing output path:

   - model `to_json()`
   - REST schemas
   - JSONL writers
   - `index.json` writers
   - admin config/debug views
   - live-progress payloads
   - CLI config output
   - replay command rendering
   - process/env rendering

   Rule: raw internal config requires an explicit internal method/argument. Public/export methods redact by default.

## Validation Plan

Use real code paths only.

1. Create a real persona with sensitive config:

   - `TWOCAPTCHA_API_KEY`
   - `ANTHROPIC_API_KEY`
   - cookie/auth paths
   - a custom user agent
   - plugin overrides

2. Create crawls via:

   - `/add/`
   - CLI `archivebox add`
   - REST API
   - schedule enqueue

3. Assert DB behavior:

   - `Crawl.config` contains the fully resolved runtime config.
   - Sensitive raw values exist in DB where runtime needs them.
   - `Snapshot.config` only contains snapshot-local overrides.
   - Later persona/user/machine config edits do not mutate old `Crawl.config`.
   - Manual edits to `Crawl.config` affect subsequent snapshots in that crawl.

4. Assert runtime behavior:

   - Hooks receive raw values from frozen crawl config.
   - Persona cookies/auth/user-agent values work for real browser-backed crawls.
   - New discovered snapshots inherit the crawl config.

5. Assert no leakage:

   - REST crawl/persona responses show `********`.
   - Admin/persona/crawl/snapshot pages do not include raw secrets.
   - `/add/` persona hydration JSON does not include raw secrets.
   - `index.json` and `index.jsonl` do not include raw secrets.
   - exported JSONL does not include raw secrets.
   - live-progress JSON/HTML does not include raw secrets.
   - replay commands redact sensitive env/config values.
   - access logs redact sensitive query params.

6. Performance check:

   - Crawl/snapshot runner hot paths no longer query persona/user/machine just to resolve archive config.
   - live-progress does not resolve full per-crawl config chains.
   - admin snapshot/crawl list pages avoid per-row dynamic config resolution where frozen config is enough.

## Things Not To Do

- Do not redact values before storing them in DB if hooks need them.
- Do not store only overrides on `Crawl.config`.
- Do not continue walking persona/user/machine/env defaults beneath a frozen crawl.
- Do not add scattered one-off masking logic.
- Do not introduce compatibility branches for stale dev-only config shapes if a migration/backfill can clean them.
- Do not change request/UI/server config resolution blindly; server/UI settings still need current request/global config in many views.
- Do not leak raw config through helper methods named like `to_json`, `as_dict`, `payload`, `context`, or `export`.
